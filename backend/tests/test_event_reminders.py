"""
Termin-Erinnerungen (PD-K1, P3).

- Feld ``reminder`` pro Termin: none | 15m | 1h | 1d (Default none).
- Push an die Teilnehmer (aktuelle Mitglieder), sonst an alle Mitglieder.
- Ganztägig: 08:00 Haushaltszeit am Tag (1d → 08:00 am Vortag).
- Genau einmal (notified_at-Claim); Zurücksetzen, wenn Zeit oder Erinnerung geändert wird.
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models import Event, HouseholdMember, PushSubscription
from app.services import push_service

FCM = "https://fcm.googleapis.com/fcm/send/"


@pytest.fixture()
def mock_webpush():
    with patch("app.services.push_service.webpush") as m:
        yield m


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _add_sub(db, user, locale="de"):
    sub = PushSubscription(
        user_id=user.id, endpoint=FCM + uuid.uuid4().hex, p256dh="p256", auth="authsecret", locale=locale
    )
    db.add(sub)
    db.commit()
    return sub


def _payloads(mock):
    return [json.loads(c.kwargs["data"]) for c in mock.call_args_list]


def _create(client, household, token, calendar, **fields):
    body = {"title": "Zahnarzt", "calendar_id": str(calendar.id), **fields}
    resp = client.post(f"/api/households/{household.id}/events/", headers=_auth(token), json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_reminder_defaults_to_none(client, household_a, token_a, calendar_a):
    ev = _create(client, household_a, token_a, calendar_a, starts_at="2026-10-07T09:00:00")
    assert ev["reminder"] == "none"


def test_reminder_values_validated(client, household_a, token_a, calendar_a):
    resp = client.post(
        f"/api/households/{household_a.id}/events/", headers=_auth(token_a),
        json={"title": "X", "calendar_id": str(calendar_a.id), "starts_at": "2026-10-07T09:00:00",
              "reminder": "2h"},
    )
    assert resp.status_code == 422
    ev = _create(client, household_a, token_a, calendar_a, starts_at="2026-10-07T09:00:00", reminder="1h")
    resp = client.patch(
        f"/api/households/{household_a.id}/events/{ev['id']}", headers=_auth(token_a), json={"reminder": None}
    )
    assert resp.status_code == 422


def test_change_of_time_or_reminder_resets_claim(client, db, household_a, token_a, calendar_a):
    ev = _create(client, household_a, token_a, calendar_a, starts_at="2026-10-07T09:00:00", reminder="1h")
    url = f"/api/households/{household_a.id}/events/{ev['id']}"

    def mark_sent():
        row = db.get(Event, uuid.UUID(ev["id"]))
        row.notified_at = datetime.now(timezone.utc)
        db.commit()

    def notified():
        db.expire_all()
        return db.get(Event, uuid.UUID(ev["id"])).notified_at

    mark_sent()
    client.patch(url, headers=_auth(token_a), json={"title": "Umbenannt"})
    assert notified() is not None  # Titel ändert nichts

    client.patch(url, headers=_auth(token_a), json={"starts_at": "2026-10-07T09:00:00"})
    assert notified() is not None  # gleiche Zeit zurückgeschickt → keine Änderung

    client.patch(url, headers=_auth(token_a), json={"starts_at": "2026-10-08T09:00:00"})
    assert notified() is None

    mark_sent()
    client.patch(url, headers=_auth(token_a), json={"reminder": "15m"})
    assert notified() is None

    mark_sent()
    client.patch(url, headers=_auth(token_a), json={"all_day": True})
    assert notified() is None


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


def _event(db, household, user, calendar, starts_at, reminder, all_day=False, participants=()):
    e = Event(
        household_id=household.id, calendar_id=calendar.id, title="Zahnarzt", starts_at=starts_at,
        all_day=all_day, participant_ids=[str(p) for p in participants], created_by_user_id=user.id,
        reminder=reminder,
    )
    db.add(e)
    db.commit()
    return e


def test_timed_reminder_sent_once_to_all_members(db, household_a, user_a, user_a2, user_b, calendar_a, mock_webpush):
    _add_sub(db, user_a)
    _add_sub(db, user_a2)
    _add_sub(db, user_b)  # anderer Haushalt
    e = _event(db, household_a, user_a, calendar_a, _utc(2026, 10, 7, 7, 0), "15m")  # 09:00 Zürich

    assert push_service.process_event_reminders(db, _utc(2026, 10, 7, 6, 44)) == 0
    assert push_service.process_event_reminders(db, _utc(2026, 10, 7, 6, 45)) == 2
    payload = _payloads(mock_webpush)[0]
    assert payload["title"] == "Termin in 15 Minuten"
    assert payload["body"] == "Zahnarzt · 09:00"
    assert payload["url"] == "/calendar"
    db.refresh(e)
    assert e.notified_at is not None

    mock_webpush.reset_mock()
    assert push_service.process_event_reminders(db, _utc(2026, 10, 7, 6, 50)) == 0
    mock_webpush.assert_not_called()


def test_reminder_goes_to_current_participants(db, household_a, user_a, user_a2, calendar_a, mock_webpush):
    _add_sub(db, user_a)
    sub2 = _add_sub(db, user_a2, locale="en")
    _event(db, household_a, user_a, calendar_a, _utc(2026, 10, 7, 7, 0), "1h", participants=[user_a2.id])

    assert push_service.process_event_reminders(db, _utc(2026, 10, 7, 6, 0)) == 1
    assert mock_webpush.call_args.kwargs["subscription_info"]["endpoint"] == sub2.endpoint
    assert _payloads(mock_webpush)[0]["title"] == "Event in 1 hour"


def test_ex_member_participants_fall_back_to_all(db, household_a, user_a, user_a2, calendar_a, mock_webpush):
    _add_sub(db, user_a)
    _add_sub(db, user_a2)
    _event(db, household_a, user_a, calendar_a, _utc(2026, 10, 7, 7, 0), "1h", participants=[user_a2.id])
    db.query(HouseholdMember).filter_by(household_id=household_a.id, user_id=user_a2.id).delete()
    db.commit()

    assert push_service.process_event_reminders(db, _utc(2026, 10, 7, 6, 0)) == 1  # nur noch user_a


def test_one_day_before(db, household_a, user_a, calendar_a, mock_webpush):
    _add_sub(db, user_a)
    _event(db, household_a, user_a, calendar_a, _utc(2026, 10, 7, 7, 0), "1d")
    assert push_service.process_event_reminders(db, _utc(2026, 10, 6, 6, 59)) == 0
    assert push_service.process_event_reminders(db, _utc(2026, 10, 6, 7, 0)) == 1
    assert _payloads(mock_webpush)[0]["title"] == "Termin morgen"


def test_all_day_reminds_at_eight_local(db, household_a, user_a, calendar_a, mock_webpush):
    _add_sub(db, user_a)
    # Ganztägig am 07.10. (00:00 Zürich = 06.10. 22:00 UTC)
    _event(db, household_a, user_a, calendar_a, _utc(2026, 10, 6, 22, 0), "15m", all_day=True)
    assert push_service.process_event_reminders(db, _utc(2026, 10, 7, 5, 59)) == 0  # 07:59 Zürich
    assert push_service.process_event_reminders(db, _utc(2026, 10, 7, 6, 0)) == 1   # 08:00 Zürich
    payload = _payloads(mock_webpush)[0]
    assert payload["title"] == "Termin heute"
    assert payload["body"] == "Zahnarzt"


def test_all_day_one_day_before_at_eight(db, household_a, user_a, calendar_a, mock_webpush):
    _add_sub(db, user_a)
    _event(db, household_a, user_a, calendar_a, _utc(2026, 10, 6, 22, 0), "1d", all_day=True)
    assert push_service.process_event_reminders(db, _utc(2026, 10, 6, 5, 59)) == 0
    assert push_service.process_event_reminders(db, _utc(2026, 10, 6, 6, 0)) == 1
    assert _payloads(mock_webpush)[0]["title"] == "Termin morgen"


def test_none_reminder_never_sent(db, household_a, user_a, calendar_a, mock_webpush):
    _add_sub(db, user_a)
    _event(db, household_a, user_a, calendar_a, _utc(2026, 10, 7, 7, 0), "none")
    assert push_service.process_event_reminders(db, _utc(2026, 10, 7, 6, 59)) == 0


def test_started_or_stale_claimed_but_not_sent(db, household_a, user_a, calendar_a, mock_webpush):
    """Backend war offline: Termin hat schon begonnen → still als erledigt markieren."""
    _add_sub(db, user_a)
    e = _event(db, household_a, user_a, calendar_a, _utc(2026, 10, 7, 7, 0), "1h")
    assert push_service.process_event_reminders(db, _utc(2026, 10, 7, 7, 5)) == 0
    mock_webpush.assert_not_called()
    db.refresh(e)
    assert e.notified_at is not None
