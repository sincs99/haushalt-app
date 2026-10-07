"""
Web Push für Putzplan ("Du bist dran") und Ablaufdaten von Dokumenten,
sowie die Zahl am App-Icon (Badge) in Push-Payload und API.

webpush() wird gemockt — es werden nie echte HTTP-Requests gesendet.
"""

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models import (
    Chore,
    ChoreAssignment,
    Document,
    PlantCareTask,
    PushSubscription,
    Todo,
)
from app.services import push_service
from app.services.attention import attention_count, household_today

FCM = "https://fcm.googleapis.com/fcm/send/"

# 09:00 in Zürich (Sommerzeit, UTC+2) bzw. 06:00 (vor der Meldestunde)
MORNING = datetime(2026, 9, 29, 7, 0, tzinfo=timezone.utc)
EARLY = datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc)
DAY = date(2026, 9, 29)


@pytest.fixture()
def mock_webpush():
    with patch("app.services.push_service.webpush") as m:
        yield m


@pytest.fixture(autouse=True)
def _reset_materialized():
    push_service._chores_materialized.clear()
    yield
    push_service._chores_materialized.clear()


@pytest.fixture()
def zurich(db, household_a):
    household_a.timezone = "Europe/Zurich"
    db.commit()
    return household_a


def _add_sub(db, user, locale="de"):
    sub = PushSubscription(
        user_id=user.id, endpoint=FCM + uuid.uuid4().hex,
        p256dh="p256", auth="authsecret", locale=locale,
    )
    db.add(sub)
    db.commit()
    return sub


def _payloads(mock):
    return [json.loads(c.kwargs["data"]) for c in mock.call_args_list]


def _endpoints(mock):
    return {c.kwargs["subscription_info"]["endpoint"] for c in mock.call_args_list}


def _chore(db, household, user_ids, title="Bad putzen", active=True):
    chore = Chore(
        household_id=household.id, title=title, recurrence="weekly", weekday=DAY.weekday(),
        rotation_order=[str(u) for u in user_ids], anchor_date=DAY - timedelta(days=7), active=active,
    )
    db.add(chore)
    db.commit()
    return chore


def _assignment(db, chore, due: date, user_id=None):
    a = ChoreAssignment(
        household_id=chore.household_id, chore_id=chore.id, assigned_user_id=user_id, due_date=due,
    )
    db.add(a)
    db.commit()
    return a


def _no_materialize():
    # Feste Testzeit: die echte Materialisierung rechnet mit dem heutigen Datum
    return patch("app.services.push_service._ensure_chore_assignments")


# ---------------------------------------------------------------------------
# Putzplan: "Du bist dran"
# ---------------------------------------------------------------------------
def test_chore_notifies_assignee_once_in_the_morning(db, zurich, user_a, user_a2, mock_webpush):
    sub_a = _add_sub(db, user_a)
    _add_sub(db, user_a2)
    chore = _chore(db, zurich, [user_a.id])
    assignment = _assignment(db, chore, DAY, user_a.id)

    with _no_materialize():
        assert push_service.process_chore_assignments(db, EARLY) == 0
        db.refresh(assignment)
        assert assignment.notified_at is None

        assert push_service.process_chore_assignments(db, MORNING) == 1
        assert _endpoints(mock_webpush) == {sub_a.endpoint}
        payload = _payloads(mock_webpush)[0]
        assert payload["title"] == "Du bist dran"
        assert payload["body"] == "Bad putzen"
        assert payload["url"] == "/chores"
        assert payload["badge"] == 1

        mock_webpush.reset_mock()
        assert push_service.process_chore_assignments(db, MORNING) == 0


def test_unassigned_chore_goes_to_all_members(db, zurich, user_a, user_a2, user_b, mock_webpush):
    _add_sub(db, user_a)
    _add_sub(db, user_a2)
    _add_sub(db, user_b)  # anderer Haushalt
    chore = _chore(db, zurich, [user_a.id])
    _assignment(db, chore, DAY, None)

    with _no_materialize():
        assert push_service.process_chore_assignments(db, MORNING) == 2
    assert {p["title"] for p in _payloads(mock_webpush)} == {"Ämtli heute fällig"}


def test_done_past_and_future_chores_not_notified(db, zurich, user_a, mock_webpush):
    _add_sub(db, user_a)
    chore = _chore(db, zurich, [user_a.id])
    done = _assignment(db, chore, DAY, user_a.id)
    done.completed_at = MORNING
    db.commit()
    _assignment(db, chore, DAY - timedelta(days=1), user_a.id)
    _assignment(db, chore, DAY + timedelta(days=1), user_a.id)

    with _no_materialize():
        assert push_service.process_chore_assignments(db, MORNING) == 0
    mock_webpush.assert_not_called()


def test_chore_locale_en(db, zurich, user_a, mock_webpush):
    _add_sub(db, user_a, locale="en")
    chore = _chore(db, zurich, [user_a.id], title="Take out trash")
    _assignment(db, chore, DAY, user_a.id)
    with _no_materialize():
        push_service.process_chore_assignments(db, MORNING)
    assert _payloads(mock_webpush)[0]["title"] == "It's your turn"


def test_scheduler_materializes_todays_chore(db, zurich, user_a, mock_webpush):
    """Ohne dass jemand den Putzplan geöffnet hat, entsteht das heutige Ämtli."""
    _add_sub(db, user_a)
    db.add(Chore(
        household_id=zurich.id, title="Abfall", recurrence="weekly", weekday=DAY.weekday(),
        rotation_order=[str(user_a.id)], anchor_date=DAY, active=True,
    ))
    db.commit()

    with patch("app.services.chore_scheduler.today_in_tz", return_value=DAY):
        assert push_service.process_chore_assignments(db, EARLY) == 0
        assert db.query(ChoreAssignment).count() == 0  # vor 08:00 nichts anlegen

        assert push_service.process_chore_assignments(db, MORNING) == 1
        assert any(a.due_date == DAY for a in db.query(ChoreAssignment).all())
        assert _payloads(mock_webpush)[0]["title"] == "Du bist dran"
        # Zweiter Lauf am selben Tag sendet nichts mehr
        assert push_service.process_chore_assignments(db, MORNING) == 0


# ---------------------------------------------------------------------------
# Dokumente: Ablaufdatum
# ---------------------------------------------------------------------------
def _document(db, household, expiry: date | None, title="Garantie Waschmaschine", category="warranty"):
    doc = Document(household_id=household.id, title=title, category=category, expiry_date=expiry)
    db.add(doc)
    db.commit()
    return doc


def test_document_lead_warning_then_due_day(db, zurich, user_a, user_a2, mock_webpush):
    _add_sub(db, user_a)
    _add_sub(db, user_a2)
    doc = _document(db, zurich, DAY + timedelta(days=30))

    assert push_service.process_document_expiry(db, EARLY) == 0
    assert push_service.process_document_expiry(db, MORNING) == 2
    payload = _payloads(mock_webpush)[0]
    assert payload["title"] == "Dokument läuft bald ab"
    assert payload["body"] == "Garantie Waschmaschine · 29.10.2026"
    assert payload["url"] == "/documents"
    assert "badge" in payload

    mock_webpush.reset_mock()
    # Bis zum Ablauftag keine weitere Meldung
    assert push_service.process_document_expiry(db, MORNING + timedelta(days=10)) == 0

    # Am Ablauftag
    assert push_service.process_document_expiry(db, MORNING + timedelta(days=30)) == 2
    assert _payloads(mock_webpush)[0]["title"] == "Dokument läuft heute ab"
    db.refresh(doc)
    assert doc.expiry_notified_at is not None

    mock_webpush.reset_mock()
    assert push_service.process_document_expiry(db, MORNING + timedelta(days=30)) == 0


def test_document_far_future_or_past_not_notified(db, zurich, user_a, mock_webpush):
    _add_sub(db, user_a)
    _document(db, zurich, DAY + timedelta(days=31))
    _document(db, zurich, DAY - timedelta(days=1))
    _document(db, zurich, None)
    assert push_service.process_document_expiry(db, MORNING) == 0
    mock_webpush.assert_not_called()


def test_document_created_close_to_expiry_gets_warning(db, zurich, user_a, mock_webpush):
    _add_sub(db, user_a)
    _document(db, zurich, DAY + timedelta(days=3))
    assert push_service.process_document_expiry(db, MORNING) == 1
    assert _payloads(mock_webpush)[0]["title"] == "Dokument läuft bald ab"


def test_document_locale_en_date_format(db, zurich, user_a, mock_webpush):
    _add_sub(db, user_a, locale="en")
    _document(db, zurich, DAY, title="Phone contract", category="contract")
    push_service.process_document_expiry(db, MORNING)
    payload = _payloads(mock_webpush)[0]
    assert payload["title"] == "Document expires today"
    assert payload["body"] == "Phone contract · 2026-09-29"


def test_changing_expiry_resets_notifications(client, db, household_a, user_a, token_a):
    doc = _document(db, household_a, DAY)
    doc.expiry_soon_notified_at = MORNING
    doc.expiry_notified_at = MORNING
    db.commit()

    r = client.patch(
        f"/api/households/{household_a.id}/documents/{doc.id}",
        json={"title": "Neuer Titel"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 200
    db.refresh(doc)
    assert doc.expiry_notified_at is not None  # Titel allein ändert nichts

    r = client.patch(
        f"/api/households/{household_a.id}/documents/{doc.id}",
        json={"expiry_date": (DAY + timedelta(days=365)).isoformat()},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 200
    db.refresh(doc)
    assert doc.expiry_soon_notified_at is None
    assert doc.expiry_notified_at is None


# ---------------------------------------------------------------------------
# Badge (Zahl am App-Icon)
# ---------------------------------------------------------------------------
def test_attention_count_per_user(db, household_a, user_a, user_a2, plant_a):
    today = household_today(household_a)
    now = datetime.now(timezone.utc)
    # Todos: fällig (mir), fällig (niemand), fällig (anderer), ohne Datum, erledigt, Zukunft
    db.add_all([
        Todo(household_id=household_a.id, title="mine", created_by_user_id=user_a.id,
             assigned_to_user_id=user_a.id, due_date=now - timedelta(hours=1)),
        Todo(household_id=household_a.id, title="open", created_by_user_id=user_a.id,
             due_date=now - timedelta(days=2)),
        Todo(household_id=household_a.id, title="other", created_by_user_id=user_a.id,
             assigned_to_user_id=user_a2.id, due_date=now - timedelta(hours=1)),
        Todo(household_id=household_a.id, title="nodate", created_by_user_id=user_a.id),
        Todo(household_id=household_a.id, title="done", created_by_user_id=user_a.id,
             due_date=now - timedelta(hours=1), is_done=True),
        Todo(household_id=household_a.id, title="future", created_by_user_id=user_a.id,
             due_date=now + timedelta(days=3)),
    ])
    chore = _chore(db, household_a, [user_a.id])
    _assignment(db, chore, today, user_a.id)
    _assignment(db, chore, today - timedelta(days=1), user_a2.id)
    _assignment(db, chore, today + timedelta(days=1), user_a.id)
    db.add(PlantCareTask(household_id=household_a.id, plant_id=plant_a.id, care_type="water",
                         interval_days=7, next_due_at=today))
    db.commit()

    # user_a: mine + open + Ämtli heute + Pflanze = 4
    assert attention_count(db, household_a, user_a.id) == 4
    # user_a2: other + open + Ämtli gestern + Pflanze = 4
    assert attention_count(db, household_a, user_a2.id) == 4


def test_badge_endpoint(client, db, household_a, user_a, token_a, token_b):
    db.add(Todo(household_id=household_a.id, title="x", created_by_user_id=user_a.id,
                due_date=datetime.now(timezone.utc) - timedelta(hours=1)))
    db.commit()
    url = f"/api/households/{household_a.id}/dashboard/badge"
    r = client.get(url, headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200
    assert r.json() == {"count": 1}
    # Fremder Haushalt: kein Zugriff
    r = client.get(url, headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code in (403, 404)
