"""Tags (NFC/QR): Verwaltung, Resolve/Execute je Aktion, Scoping, Rate-Limit, Logs."""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.core.log_redaction import TagTokenRedactionFilter, redact_tag_tokens
from app.core.rate_limit import limiter
from app.models import (
    Chore,
    ChoreAssignment,
    FeedingLog,
    PetCareTask,
    ShoppingList,
    Tag,
    Todo,
)
from app.routers.tags import MAX_TAGS_PER_HOUSEHOLD, generate_tag_token
from app.services import tag_actions
from app.services.chore_scheduler import today_in_tz
from app.services.tag_actions import TAG_ACTIONS


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _tags_url(household) -> str:
    return f"/api/households/{household.id}/tags/"


def _make_tag(db, household, action, target_type, target_id=None, *, enabled=True, label="Chip") -> Tag:
    tag = Tag(
        household_id=household.id,
        token=generate_tag_token(),
        label=label,
        target_type=target_type,
        target_id=target_id,
        action=action,
        enabled=enabled,
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def _resolve(client, token, tag):
    return client.post(f"/api/tags/resolve/{tag.token}", headers=_auth(token))


def _execute(client, token, tag, body=None):
    return client.post(f"/api/tags/{tag.token}/execute", headers=_auth(token), json=body)


@pytest.fixture()
def care_task_a(db, household_a, pet_a) -> PetCareTask:
    task = PetCareTask(
        household_id=household_a.id,
        pet_id=pet_a.id,
        name="Krallen schneiden",
        interval_days=14,
        next_due_at=date(2026, 1, 1),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@pytest.fixture()
def chore_a(db, household_a, user_a) -> Chore:
    today = today_in_tz(household_a.timezone)
    chore = Chore(
        household_id=household_a.id,
        title="Bad putzen",
        recurrence="weekly",
        weekday=today.weekday(),
        rotation_order=[str(user_a.id)],
        next_rotation_index=0,
        anchor_date=today,
        active=True,
        created_by_user_id=user_a.id,
    )
    db.add(chore)
    db.commit()
    db.refresh(chore)
    return chore


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------


def test_token_is_random_url_safe_and_long():
    tokens = {generate_tag_token() for _ in range(200)}
    assert len(tokens) == 200
    for t in tokens:
        assert len(t) == 32  # 24 Byte = 192 Bit
        assert all(c.isalnum() or c in "-_" for c in t)


def test_registry_has_no_delete_actions():
    for key in TAG_ACTIONS:
        assert "delete" not in key and "remove" not in key


# ---------------------------------------------------------------------------
# CRUD + Rollen
# ---------------------------------------------------------------------------


class TestTagCrud:
    def test_admin_creates_tag(self, client, household_a, token_a, pet_a, _mock_socket_emit):
        resp = client.post(
            _tags_url(household_a),
            headers=_auth(token_a),
            json={"label": " Futternapf ", "target_type": "pet", "target_id": str(pet_a.id), "action": "pet.feed"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["label"] == "Futternapf"
        assert data["target_name"] == "Luna"
        assert data["use_count"] == 0
        assert data["enabled"] is True
        assert len(data["token"]) == 32
        events = [c.args[1] for c in _mock_socket_emit.call_args_list]
        assert "tag_created" in events

    def test_member_cannot_create(self, client, household_a, token_a2, pet_a):
        resp = client.post(
            _tags_url(household_a),
            headers=_auth(token_a2),
            json={"label": "X", "target_type": "pet", "target_id": str(pet_a.id), "action": "pet.feed"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "ADMIN_REQUIRED"

    def test_member_can_list(self, client, db, household_a, token_a2, pet_a):
        _make_tag(db, household_a, "pet.feed", "pet", pet_a.id)
        resp = client.get(_tags_url(household_a), headers=_auth(token_a2))
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_member_cannot_update_regenerate_or_delete(self, client, db, household_a, token_a2, pet_a):
        tag = _make_tag(db, household_a, "pet.feed", "pet", pet_a.id)
        url = f"{_tags_url(household_a)}{tag.id}"
        assert client.patch(url, headers=_auth(token_a2), json={"enabled": False}).status_code == 403
        assert client.post(f"{url}/regenerate-token", headers=_auth(token_a2)).status_code == 403
        assert client.delete(url, headers=_auth(token_a2)).status_code == 403

    def test_action_must_match_target_type(self, client, household_a, token_a, pet_a):
        resp = client.post(
            _tags_url(household_a),
            headers=_auth(token_a),
            json={"label": "X", "target_type": "todo", "target_id": str(pet_a.id), "action": "pet.feed"},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "TAG_ACTION_INVALID"

    def test_unknown_action_rejected(self, client, household_a, token_a, todo_a):
        resp = client.post(
            _tags_url(household_a),
            headers=_auth(token_a),
            json={"label": "X", "target_type": "todo", "target_id": str(todo_a.id), "action": "todo.delete"},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "TAG_ACTION_INVALID"

    def test_target_from_other_household_rejected(self, client, household_a, token_a, pet_b):
        resp = client.post(
            _tags_url(household_a),
            headers=_auth(token_a),
            json={"label": "X", "target_type": "pet", "target_id": str(pet_b.id), "action": "pet.feed"},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "TAG_TARGET_INVALID"

    def test_target_required_unless_optional(self, client, household_a, token_a):
        resp = client.post(
            _tags_url(household_a),
            headers=_auth(token_a),
            json={"label": "X", "target_type": "todo", "action": "todo.done"},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "TAG_TARGET_INVALID"
        # pet.feed ohne Ziel = alle Tiere
        resp = client.post(
            _tags_url(household_a),
            headers=_auth(token_a),
            json={"label": "Alle", "target_type": "pet", "action": "pet.feed"},
        )
        assert resp.status_code == 201
        assert resp.json()["target_id"] is None

    def test_cross_household_management_forbidden(self, client, db, household_a, token_b, pet_a):
        tag = _make_tag(db, household_a, "pet.feed", "pet", pet_a.id)
        url = _tags_url(household_a)
        assert client.get(url, headers=_auth(token_b)).status_code == 403
        assert client.get(f"{url}targets", headers=_auth(token_b)).status_code == 403
        assert client.patch(f"{url}{tag.id}", headers=_auth(token_b), json={"label": "Y"}).status_code == 403
        assert client.delete(f"{url}{tag.id}", headers=_auth(token_b)).status_code == 403

    def test_tag_id_of_other_household_is_404(self, client, db, household_a, household_b, token_a, user_b, pet_b):
        tag_b = _make_tag(db, household_b, "pet.feed", "pet", pet_b.id)
        resp = client.patch(f"{_tags_url(household_a)}{tag_b.id}", headers=_auth(token_a), json={"label": "Y"})
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "TAG_NOT_FOUND"

    def test_update_label_enabled_and_retarget(self, client, db, household_a, token_a, pet_a, todo_a, _mock_socket_emit):
        tag = _make_tag(db, household_a, "pet.feed", "pet", pet_a.id)
        url = f"{_tags_url(household_a)}{tag.id}"
        resp = client.patch(url, headers=_auth(token_a), json={"label": "Neu", "enabled": False})
        assert resp.status_code == 200
        assert resp.json()["label"] == "Neu"
        assert resp.json()["enabled"] is False
        # Neu zuordnen ohne passende Aktion → 422
        resp = client.patch(url, headers=_auth(token_a), json={"target_type": "todo", "target_id": str(todo_a.id)})
        assert resp.status_code == 422
        resp = client.patch(
            url,
            headers=_auth(token_a),
            json={"target_type": "todo", "target_id": str(todo_a.id), "action": "todo.done"},
        )
        assert resp.status_code == 200
        assert resp.json()["target_name"] == "Küche putzen"
        assert "tag_updated" in [c.args[1] for c in _mock_socket_emit.call_args_list]

    def test_regenerate_token_invalidates_old(self, client, db, household_a, token_a, pet_a):
        tag = _make_tag(db, household_a, "pet.feed", "pet", pet_a.id)
        old = tag.token
        resp = client.post(f"{_tags_url(household_a)}{tag.id}/regenerate-token", headers=_auth(token_a))
        assert resp.status_code == 200
        new = resp.json()["token"]
        assert new != old
        assert client.post(f"/api/tags/resolve/{old}", headers=_auth(token_a)).status_code == 404
        assert client.post(f"/api/tags/resolve/{new}", headers=_auth(token_a)).status_code == 200

    def test_delete(self, client, db, household_a, token_a, pet_a, _mock_socket_emit):
        tag = _make_tag(db, household_a, "pet.feed", "pet", pet_a.id)
        resp = client.delete(f"{_tags_url(household_a)}{tag.id}", headers=_auth(token_a))
        assert resp.status_code == 204
        assert db.query(Tag).count() == 0
        assert "tag_deleted" in [c.args[1] for c in _mock_socket_emit.call_args_list]

    def test_limit_per_household(self, client, db, household_a, token_a, pet_a):
        db.add_all(
            Tag(
                household_id=household_a.id,
                token=generate_tag_token(),
                label=f"T{i}",
                target_type="pet",
                action="pet.feed",
            )
            for i in range(MAX_TAGS_PER_HOUSEHOLD)
        )
        db.commit()
        resp = client.post(
            _tags_url(household_a),
            headers=_auth(token_a),
            json={"label": "X", "target_type": "pet", "action": "pet.feed"},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "TOO_MANY_TAGS"

    def test_targets_endpoint(self, client, db, household_a, token_a, pet_a, todo_a, shopping_list_a, care_task_a, chore_a):
        resp = client.get(f"{_tags_url(household_a)}targets", headers=_auth(token_a))
        assert resp.status_code == 200
        by_type = {t["target_type"]: t for t in resp.json()}
        assert set(by_type) == {"pet", "pet_care_task", "chore", "shopping_list", "todo"}
        assert by_type["pet"]["options"] == [{"id": str(pet_a.id), "name": "Luna"}]
        assert by_type["pet_care_task"]["options"][0]["name"] == "Luna – Krallen schneiden"
        assert by_type["shopping_list"]["actions"] == [
            {"key": "shopping_list.open", "target_optional": True, "navigate_only": True}
        ]

    def test_deleted_target_marked_missing(self, client, db, household_a, token_a, todo_a):
        _make_tag(db, household_a, "todo.done", "todo", todo_a.id)
        db.delete(todo_a)
        db.commit()
        resp = client.get(_tags_url(household_a), headers=_auth(token_a))
        assert resp.json()[0]["target_missing"] is True


# ---------------------------------------------------------------------------
# Resolve / Execute — Fehlerfälle
# ---------------------------------------------------------------------------


class TestScanErrors:
    def test_unknown_token_404(self, client, token_a):
        resp = client.post("/api/tags/resolve/does-not-exist", headers=_auth(token_a))
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "TAG_NOT_FOUND"
        resp = client.post("/api/tags/does-not-exist/execute", headers=_auth(token_a))
        assert resp.status_code == 404

    def test_overlong_token_404(self, client, token_a):
        resp = client.post(f"/api/tags/resolve/{'a' * 500}", headers=_auth(token_a))
        assert resp.status_code == 404

    def test_requires_login(self, client, db, household_a, pet_a):
        tag = _make_tag(db, household_a, "pet.feed", "pet", pet_a.id)
        assert client.post(f"/api/tags/resolve/{tag.token}").status_code == 401
        assert client.post(f"/api/tags/{tag.token}/execute").status_code == 401

    def test_foreign_household_403(self, client, db, household_a, token_b, pet_a):
        tag = _make_tag(db, household_a, "pet.feed", "pet", pet_a.id)
        resp = _resolve(client, token_b, tag)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "NOT_HOUSEHOLD_MEMBER"
        assert _execute(client, token_b, tag).status_code == 403
        assert db.query(FeedingLog).count() == 0

    def test_foreign_household_403_even_if_disabled(self, client, db, household_a, token_b, pet_a):
        tag = _make_tag(db, household_a, "pet.feed", "pet", pet_a.id, enabled=False)
        assert _resolve(client, token_b, tag).status_code == 403

    def test_disabled_tag_410(self, client, db, household_a, token_a, pet_a):
        tag = _make_tag(db, household_a, "pet.feed", "pet", pet_a.id, enabled=False)
        resp = _resolve(client, token_a, tag)
        assert resp.status_code == 410
        assert resp.json()["detail"]["code"] == "TAG_DISABLED"
        assert _execute(client, token_a, tag).status_code == 410
        assert db.query(FeedingLog).count() == 0

    def test_deleted_target_404(self, client, db, household_a, token_a, todo_a):
        tag = _make_tag(db, household_a, "todo.done", "todo", todo_a.id)
        db.delete(todo_a)
        db.commit()
        resp = _resolve(client, token_a, tag)
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "TAG_TARGET_NOT_FOUND"

    def test_unsupported_action_422(self, client, db, household_a, token_a):
        tag = _make_tag(db, household_a, "plant.water", "plant")
        resp = _resolve(client, token_a, tag)
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "TAG_ACTION_INVALID"

    def test_resolve_does_not_mutate(self, client, db, household_a, token_a, todo_a):
        tag = _make_tag(db, household_a, "todo.done", "todo", todo_a.id)
        assert _resolve(client, token_a, tag).status_code == 200
        db.refresh(todo_a)
        db.refresh(tag)
        assert todo_a.is_done is False
        assert tag.use_count == 0
        assert tag.last_used_at is None


# ---------------------------------------------------------------------------
# Aktionen
# ---------------------------------------------------------------------------


class TestPetFeed:
    def test_resolve_and_execute_single_pet(self, client, db, household_a, token_a, user_a, pet_a, _mock_socket_emit):
        tag = _make_tag(db, household_a, "pet.feed", "pet", pet_a.id)
        resp = _resolve(client, token_a, tag)
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "pet.feed"
        assert data["target_name"] == "Luna"
        assert data["household_name"] == "Haushalt Alpha"
        assert data["navigate_only"] is False
        assert data["can_execute"] is True
        assert data["details"]["slot"] in ("morning", "evening")
        assert data["details"]["last_fed_at"] is None

        resp = _execute(client, token_a, tag, {"slot": "morning"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["changed"] is True
        assert body["result"]["slot"] == "morning"
        log = db.query(FeedingLog).one()
        assert log.pet_id == pet_a.id
        assert log.slot == "morning"
        assert log.fed_by_user_id == user_a.id
        db.refresh(tag)
        assert tag.use_count == 1
        assert tag.last_used_at is not None
        events = [c.args[1] for c in _mock_socket_emit.call_args_list]
        assert "feeding_created" in events
        assert "tag_updated" in events

    def test_second_feed_same_slot_409(self, client, db, household_a, token_a, pet_a):
        tag = _make_tag(db, household_a, "pet.feed", "pet", pet_a.id)
        assert _execute(client, token_a, tag, {"slot": "evening"}).status_code == 200
        resp = _execute(client, token_a, tag, {"slot": "evening"})
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "FEEDING_DUPLICATE"
        db.refresh(tag)
        assert tag.use_count == 1

    def test_resolve_reports_already_fed(self, client, db, household_a, token_a, pet_a):
        tag = _make_tag(db, household_a, "pet.feed", "pet", pet_a.id)
        with patch.object(tag_actions, "default_feeding_slot", return_value="morning"):
            assert _execute(client, token_a, tag).status_code == 200
            data = _resolve(client, token_a, tag).json()
        assert data["can_execute"] is False
        assert data["reason"] == "ALREADY_FED"
        assert data["details"]["last_fed_at"] is not None
        assert data["details"]["last_fed_by"] == "Alice"
        assert data["details"]["pets"][0]["morning_fed"] is True

    def test_default_slot_by_time_of_day(self, household_a):
        tz = __import__("zoneinfo").ZoneInfo(household_a.timezone)
        with patch.object(tag_actions, "_household_now", return_value=datetime(2026, 1, 1, 8, tzinfo=tz)):
            assert tag_actions.default_feeding_slot(household_a) == "morning"
        with patch.object(tag_actions, "_household_now", return_value=datetime(2026, 1, 1, 18, tzinfo=tz)):
            assert tag_actions.default_feeding_slot(household_a) == "evening"

    def test_invalid_slot_422(self, client, db, household_a, token_a, pet_a):
        tag = _make_tag(db, household_a, "pet.feed", "pet", pet_a.id)
        assert _execute(client, token_a, tag, {"slot": "noon"}).status_code == 422

    def test_feed_all_pets(self, client, db, household_a, token_a, pet_a, pet_b):
        from app.models import Pet

        db.add(Pet(household_id=household_a.id, name="Mia", species="cat"))
        db.commit()
        tag = _make_tag(db, household_a, "pet.feed", "pet", None)
        data = _resolve(client, token_a, tag).json()
        assert data["target_name"] is None
        assert [p["name"] for p in data["details"]["pets"]] == ["Luna", "Mia"]

        resp = _execute(client, token_a, tag, {"slot": "morning"})
        assert resp.status_code == 200
        assert len(resp.json()["result"]["feedings"]) == 2
        # Tier aus Haushalt B bleibt unberührt
        assert db.query(FeedingLog).filter(FeedingLog.pet_id == pet_b.id).count() == 0
        # Zweiter Scan: nichts mehr zu tun, aber kein Fehler (feed-all-Semantik)
        resp = _execute(client, token_a, tag, {"slot": "morning"})
        assert resp.status_code == 200
        assert resp.json()["changed"] is False

    def test_no_pets(self, client, db, household_a, token_a):
        tag = _make_tag(db, household_a, "pet.feed", "pet", None)
        data = _resolve(client, token_a, tag).json()
        assert data["can_execute"] is False
        assert data["reason"] == "NO_PETS"


class TestCareTaskDone:
    def test_resolve_and_execute(self, client, db, household_a, token_a, care_task_a, _mock_socket_emit):
        tag = _make_tag(db, household_a, "pet.care_task.done", "pet_care_task", care_task_a.id)
        data = _resolve(client, token_a, tag).json()
        assert data["target_name"] == "Krallen schneiden"
        assert data["details"]["pet_name"] == "Luna"
        assert data["details"]["next_due_at"] == "2026-01-01"
        assert data["can_execute"] is True

        resp = _execute(client, token_a, tag)
        assert resp.status_code == 200
        db.refresh(care_task_a)
        today = today_in_tz(household_a.timezone)
        assert care_task_a.last_done_at == today
        assert care_task_a.next_due_at == today + timedelta(days=14)
        assert "pet_care_task_updated" in [c.args[1] for c in _mock_socket_emit.call_args_list]


class TestChoreDone:
    def test_resolve_and_execute_current_assignment(self, client, db, household_a, token_a, user_a, chore_a, _mock_socket_emit):
        tag = _make_tag(db, household_a, "chore.assignment.done", "chore", chore_a.id)
        data = _resolve(client, token_a, tag).json()
        today = today_in_tz(household_a.timezone)
        assert data["target_name"] == "Bad putzen"
        assert data["can_execute"] is True
        assert data["details"]["due_date"] == today.isoformat()
        assert data["details"]["assigned_user_name"] == "Alice"

        resp = _execute(client, token_a, tag)
        assert resp.status_code == 200
        assignment = db.query(ChoreAssignment).filter(ChoreAssignment.due_date == today).one()
        assert assignment.completed_at is not None
        assert assignment.completed_by_user_id == user_a.id
        assert "chore_assignment_updated" in [c.args[1] for c in _mock_socket_emit.call_args_list]

        # Danach ist nichts mehr fällig (nächste Woche liegt ausserhalb von CHORE_EARLY_DAYS)
        data = _resolve(client, token_a, tag).json()
        assert data["can_execute"] is False
        assert data["reason"] == "NOTHING_DUE"
        assert data["details"]["last_done_by"] == "Alice"
        resp = _execute(client, token_a, tag)
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "TAG_NOTHING_TO_DO"

    def test_prefers_current_period_over_older_backlog(self, client, db, household_a, token_a, user_a, chore_a):
        today = today_in_tz(household_a.timezone)
        old = ChoreAssignment(
            household_id=household_a.id,
            chore_id=chore_a.id,
            assigned_user_id=user_a.id,
            due_date=today - timedelta(days=7),
        )
        db.add(old)
        db.commit()
        tag = _make_tag(db, household_a, "chore.assignment.done", "chore", chore_a.id)
        assert _execute(client, token_a, tag).status_code == 200
        db.refresh(old)
        assert old.completed_at is None
        current = db.query(ChoreAssignment).filter(ChoreAssignment.due_date == today).one()
        assert current.completed_at is not None

    def test_inactive_chore(self, client, db, household_a, token_a, chore_a):
        chore_a.active = False
        db.commit()
        tag = _make_tag(db, household_a, "chore.assignment.done", "chore", chore_a.id)
        data = _resolve(client, token_a, tag).json()
        assert data["can_execute"] is False
        assert data["reason"] == "CHORE_INACTIVE"
        assert _execute(client, token_a, tag).status_code == 409


class TestShoppingListOpen:
    def test_resolve_navigates_and_counts_use(self, client, db, household_a, token_a, shopping_list_a):
        tag = _make_tag(db, household_a, "shopping_list.open", "shopping_list", shopping_list_a.id)
        data = _resolve(client, token_a, tag).json()
        assert data["navigate_only"] is True
        assert data["can_execute"] is False
        assert data["navigate_to"] == f"/shopping?list={shopping_list_a.id}"
        assert data["target_name"] == "Lebensmittel"
        db.refresh(tag)
        assert tag.use_count == 1

    def test_without_list(self, client, db, household_a, token_a):
        tag = _make_tag(db, household_a, "shopping_list.open", "shopping_list", None)
        assert _resolve(client, token_a, tag).json()["navigate_to"] == "/shopping"

    def test_execute_not_allowed(self, client, db, household_a, token_a, shopping_list_a):
        tag = _make_tag(db, household_a, "shopping_list.open", "shopping_list", shopping_list_a.id)
        resp = _execute(client, token_a, tag)
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "TAG_NOT_EXECUTABLE"
        assert db.query(ShoppingList).count() == 1


class TestTodoDone:
    def test_resolve_and_execute(self, client, db, household_a, token_a2, todo_a, _mock_socket_emit):
        # Ausführen dürfen alle Mitglieder, nicht nur Admins
        tag = _make_tag(db, household_a, "todo.done", "todo", todo_a.id)
        data = _resolve(client, token_a2, tag).json()
        assert data["target_name"] == "Küche putzen"
        assert data["can_execute"] is True

        resp = _execute(client, token_a2, tag)
        assert resp.status_code == 200
        assert resp.json()["changed"] is True
        db.refresh(todo_a)
        assert todo_a.is_done is True
        assert todo_a.done_at is not None
        assert "todo_updated" in [c.args[1] for c in _mock_socket_emit.call_args_list]

    def test_already_done_is_idempotent(self, client, db, household_a, token_a, todo_a):
        done_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        todo_a.is_done = True
        todo_a.done_at = done_at
        db.commit()
        tag = _make_tag(db, household_a, "todo.done", "todo", todo_a.id)
        data = _resolve(client, token_a, tag).json()
        assert data["can_execute"] is False
        assert data["reason"] == "ALREADY_DONE"
        resp = _execute(client, token_a, tag)
        assert resp.status_code == 200
        assert resp.json()["changed"] is False
        db.refresh(todo_a)
        assert todo_a.done_at.replace(tzinfo=timezone.utc) == done_at

    def test_todo_of_other_household_cannot_be_targeted_via_db_manipulation(self, client, db, household_a, token_a, todo_b):
        # Selbst wenn ein Tag (z. B. durch einen Bug) auf ein fremdes Ziel zeigt,
        # lädt die Registry Ziele nur im Tag-Haushalt
        tag = _make_tag(db, household_a, "todo.done", "todo", todo_b.id)
        resp = _execute(client, token_a, tag)
        assert resp.status_code == 404
        db.refresh(todo_b)
        assert todo_b.is_done is False
        assert db.query(Todo).filter(Todo.is_done.is_(True)).count() == 0


# ---------------------------------------------------------------------------
# Rate-Limit
# ---------------------------------------------------------------------------


@pytest.fixture()
def _limiter_on():
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = False


@pytest.mark.parametrize(
    "route_key",
    ["app.routers.tags.resolve_tag", "app.routers.tags.execute_tag"],
)
def test_scan_endpoints_are_rate_limited(route_key):
    assert limiter._route_limits.get(route_key)


@pytest.mark.usefixtures("_limiter_on")
def test_resolve_rate_limit(client, token_a):
    for i in range(30):
        resp = client.post(f"/api/tags/resolve/guess{i}", headers=_auth(token_a))
        assert resp.status_code == 404
    resp = client.post("/api/tags/resolve/guess-last", headers=_auth(token_a))
    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "RATE_LIMITED"


@pytest.mark.usefixtures("_limiter_on")
def test_execute_rate_limit(client, token_a):
    for i in range(30):
        assert client.post(f"/api/tags/guess{i}/execute", headers=_auth(token_a)).status_code == 404
    assert client.post("/api/tags/guess/execute", headers=_auth(token_a)).status_code == 429


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


def test_redact_tag_tokens():
    assert redact_tag_tokens("POST /api/tags/resolve/abcDEF_-123 HTTP/1.1") == "POST /api/tags/resolve/*** HTTP/1.1"
    assert redact_tag_tokens("/api/tags/abc123/execute") == "/api/tags/***/execute"
    assert redact_tag_tokens("/api/households/x/tags/") == "/api/households/x/tags/"


def test_access_log_record_is_redacted():
    token = generate_tag_token()
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "POST", f"/api/tags/resolve/{token}", "1.1", 200),
        None,
    )
    TagTokenRedactionFilter().filter(record)
    assert token not in record.getMessage()
    assert "/api/tags/resolve/***" in record.getMessage()


def test_redaction_installed_on_access_logger():
    assert any(isinstance(f, TagTokenRedactionFilter) for f in logging.getLogger("uvicorn.access").filters)


def test_rate_limit_warning_does_not_leak_token(client, token_a, caplog):
    limiter.enabled = True
    limiter.reset()
    token = "secret" + uuid.uuid4().hex
    try:
        with caplog.at_level(logging.WARNING):
            for _ in range(31):
                client.post(f"/api/tags/resolve/{token}", headers=_auth(token_a))
    finally:
        limiter.reset()
        limiter.enabled = False
    assert token not in caplog.text
