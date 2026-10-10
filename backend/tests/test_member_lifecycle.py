"""
Tests für den Mitglieder-Lebenszyklus.

Stellt sicher, dass:
- entfernte/ausgetretene Mitglieder serverseitig aus dem Socket-Room fliegen,
  nachdem sie das Event noch erhalten haben
- der Einladungscode beim Entfernen erneuert wird (kein Wiederbeitritt mit altem Code)
- Admins den Code manuell erneuern können
- beim Löschen des Haushalts (letztes Mitglied tritt aus) die Dateien entfernt werden
"""

import asyncio
import uuid
from unittest.mock import patch

from app.core.security import create_access_token, hash_password
from app.models import Household, HouseholdMember, User
from app.services.storage import LocalStorageService
from app.socket_manager import emit_to_household, sio


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _add_member(db, household, email, role="member") -> User:
    user = User(id=uuid.uuid4(), email=email, password_hash=hash_password("password123"), display_name=email)
    db.add(user)
    db.flush()
    db.add(HouseholdMember(id=uuid.uuid4(), household_id=household.id, user_id=user.id, role=role))
    db.commit()
    return user


# ---------------------------------------------------------------------------
# Socket-Room: Eviction
# ---------------------------------------------------------------------------


def test_emit_with_eviction_notifies_then_removes_all_sids_of_user():
    household_id, removed, staying = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    room = f"household_{household_id}"

    async def scenario():
        mgr = sio.manager
        # Entfernter User mit zwei Verbindungen (z.B. Handy + Laptop), ein bleibender User
        sids = {}
        for name, user in (("removed_1", removed), ("removed_2", removed), ("staying", staying)):
            sid = await mgr.connect(f"eio-{name}", "/")
            await mgr.enter_room(sid, "/", f"user_{user}")
            await mgr.enter_room(sid, "/", room)
            sids[name] = sid

        sent = []

        async def record_emit(event, data, room=None, **kw):
            members = {sid for sid, _ in mgr.get_participants("/", room)}
            sent.append((event, members))

        with patch.object(sio, "emit", side_effect=record_emit):
            await emit_to_household(household_id, "household_member_removed", {"user_id": str(removed)}, removed)

        remaining = {sid for sid, _ in mgr.get_participants("/", room)}
        for sid in sids.values():
            await mgr.disconnect(sid, "/")
        return sids, sent, remaining

    sids, sent, remaining = asyncio.run(scenario())
    # Event ging noch an alle, inklusive beider Verbindungen des Entfernten
    assert sent == [("household_member_removed", set(sids.values()))]
    # Danach ist nur noch der bleibende User im Room
    assert remaining == {sids["staying"]}


def test_remove_and_leave_request_eviction(client, db, household_a, token_a, user_a, _mock_socket_emit):
    member = _add_member(db, household_a, "m@example.com")
    leaver = _add_member(db, household_a, "l@example.com")

    client.delete(f"/api/households/{household_a.id}/members/{member.id}", headers=_auth(token_a))
    client.post(f"/api/households/{household_a.id}/leave", headers=_auth(create_access_token(str(leaver.id))))

    calls = {c.args[1]: c.kwargs for c in _mock_socket_emit.call_args_list}
    assert calls["household_member_removed"] == {"evict_user_id": member.id}
    assert calls["household_member_left"] == {"evict_user_id": leaver.id}


# ---------------------------------------------------------------------------
# Einladungscode
# ---------------------------------------------------------------------------


def test_removed_member_cannot_rejoin_with_old_code(client, db, household_a, token_a, user_a):
    member = _add_member(db, household_a, "m@example.com")
    old_code = household_a.invite_code

    resp = client.delete(f"/api/households/{household_a.id}/members/{member.id}", headers=_auth(token_a))
    assert resp.status_code == 204

    db.expire_all()
    assert db.get(Household, household_a.id).invite_code != old_code

    member_token = create_access_token(str(member.id))
    resp = client.post("/api/households/join", headers=_auth(member_token), json={"invite_code": old_code})
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "INVITE_CODE_NOT_FOUND"


def test_admin_can_rotate_invite_code(client, db, household_a, token_a, user_a):
    old_code = household_a.invite_code
    resp = client.post(f"/api/households/{household_a.id}/invite-code/rotate", headers=_auth(token_a))
    assert resp.status_code == 200
    new_code = resp.json()["invite_code"]
    assert new_code != old_code

    got = client.get(f"/api/households/{household_a.id}/invite-code", headers=_auth(token_a)).json()
    assert got["invite_code"] == new_code

    outsider = User(id=uuid.uuid4(), email="o@example.com", password_hash=hash_password("password123"), display_name="O")
    db.add(outsider)
    db.commit()
    outsider_token = create_access_token(str(outsider.id))
    assert client.post("/api/households/join", headers=_auth(outsider_token), json={"invite_code": old_code}).status_code == 404
    assert client.post("/api/households/join", headers=_auth(outsider_token), json={"invite_code": new_code}).status_code == 200


def test_rotate_invite_code_requires_admin(client, household_a, token_a2, user_a):
    resp = client.post(f"/api/households/{household_a.id}/invite-code/rotate", headers=_auth(token_a2))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ADMIN_REQUIRED"


def test_rotate_invite_code_other_household_forbidden(client, household_b, token_a, user_b):
    resp = client.post(f"/api/households/{household_b.id}/invite-code/rotate", headers=_auth(token_a))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Dateien beim Löschen des Haushalts
# ---------------------------------------------------------------------------


def test_last_member_leaving_deletes_household_files(client, db, tmp_path, household_a, token_a, user_a, household_b):
    storage = LocalStorageService(str(tmp_path))
    own = storage.save(str(household_a.id), "a.pdf", b"%PDF-1", ".pdf")
    orphan = tmp_path / str(household_a.id) / "orphan.jpeg"
    orphan.write_bytes(b"x")
    other = storage.save(str(household_b.id), "b.pdf", b"%PDF-1", ".pdf")

    with patch("app.routers.households._storage", storage):
        resp = client.post(f"/api/households/{household_a.id}/leave", headers=_auth(token_a))
    assert resp.status_code == 204

    assert not (tmp_path / str(household_a.id)).exists()
    assert not (tmp_path / own).exists()
    assert (tmp_path / other).exists()  # anderer Haushalt unberührt


def test_leaving_with_remaining_members_keeps_files(client, db, tmp_path, household_a, token_a, user_a, user_a2):
    storage = LocalStorageService(str(tmp_path))
    own = storage.save(str(household_a.id), "a.pdf", b"%PDF-1", ".pdf")
    with patch("app.routers.households._storage", storage):
        resp = client.post(f"/api/households/{household_a.id}/leave", headers=_auth(token_a))
    assert resp.status_code == 204
    assert (tmp_path / own).exists()


def test_storage_refuses_to_delete_upload_root(tmp_path):
    storage = LocalStorageService(str(tmp_path))
    for bad in ("", ".", "../x"):
        try:
            storage.delete_household(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"delete_household({bad!r}) did not raise")
    assert tmp_path.exists()


def test_cleanup_deletes_upload_dirs_of_deleted_households(db, tmp_path, household_a):
    """Periodischer Cleanup: Ordner ohne Haushalt weg, bestehende und Nicht-UUID-Ordner bleiben."""
    from app.services.file_cleanup import delete_orphan_household_dirs

    storage = LocalStorageService(str(tmp_path))
    kept = storage.save(str(household_a.id), "a.pdf", b"%PDF-1", ".pdf")
    gone_id = str(uuid.uuid4())
    storage.save(gone_id, "b.pdf", b"%PDF-1", ".pdf")
    (tmp_path / "not-a-household").mkdir()

    assert delete_orphan_household_dirs(db, storage) == 1
    assert not (tmp_path / gone_id).exists()
    assert (tmp_path / kept).exists()
    assert (tmp_path / "not-a-household").exists()
