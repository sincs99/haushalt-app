"""Parallele Registrierung und Widget-Schlüssel (CASA-24) auf echtem PostgreSQL."""

import uuid

from app.models import Household, HouseholdMember, WidgetToken
from tests.pg.harness import auth_headers, run_parallel, status_codes

ROUNDS = 4


def _register(client, email, **extra):
    body = {"email": email, "password": "password123", "display_name": "Neu", **extra}
    return client.post("/api/auth/register", json=body)


def _same_email_round(client):
    email = f"race-{uuid.uuid4().hex[:8]}@example.com"
    results = run_parallel(lambda i: _register(client, email, household_name=f"HH{i}"), 4)
    codes = status_codes(results)
    assert sorted(codes) == [200, 400, 400, 400], [r.json() for r in results]
    for r in results:
        if r.status_code == 400:
            assert r.json()["detail"]["code"] == "EMAIL_ALREADY_REGISTERED"


def test_parallel_register_same_email_one_account(client):
    for _ in range(ROUNDS):
        _same_email_round(client)


def _register_vs_last_leave(client, db, hh):
    db.expire_all()
    code = db.get(Household, hh.id).invite_code
    email = f"late-{uuid.uuid4().hex[:8]}@example.com"

    def act(i):
        if i == 0:
            return client.post(hh.url("/leave"), headers=hh.headers(0))
        return _register(client, email, invite_code=code)

    leave, reg = run_parallel(act, 2)
    assert leave.status_code == 204
    assert reg.status_code in (200, 404), reg.json()
    db.expire_all()
    members = db.query(HouseholdMember).filter_by(household_id=hh.id).all()
    if reg.status_code == 200:
        assert len(members) == 1 and members[0].role == "admin"
    else:
        assert db.get(Household, hh.id) is None


def test_register_with_code_racing_last_leave(client, db, make_household):
    for _ in range(ROUNDS):
        _register_vs_last_leave(client, db, make_household(["Anna"]))


def _widget_round(client, db, hh):
    url = hh.url("/widget-token")
    results = run_parallel(lambda i: client.post(url, headers=hh.headers(0)), 4)
    assert status_codes(results) == [201] * 4, [getattr(r, "text", repr(r)) for r in results]
    db.expire_all()
    assert db.query(WidgetToken).filter_by(household_id=hh.id, user_id=hh.user_ids[0]).count() == 1
    # Genau einer der ausgegebenen Schlüssel ist gültig (neu erzeugen ersetzt den alten)
    valid = [
        r for r in results
        if client.get("/api/widget/summary", headers=auth_headers(r.json()["token"])).status_code == 200
    ]
    assert len(valid) == 1


def test_parallel_widget_token_create_leaves_one_valid_token(client, db, make_household):
    for _ in range(ROUNDS):
        _widget_round(client, db, make_household(["Anna"]))
