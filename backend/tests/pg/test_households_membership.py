"""Mitgliedschafts-Races (CASA-10, PD-H3, CASA-24 join) auf echtem PostgreSQL.

Invarianten nach jedem Ablauf:
- ≥ 1 Admin, solange der Haushalt Mitglieder hat
- Haushalt mit 0 Mitgliedern existiert nicht mehr
- 200 auf /join ⇒ der User ist danach wirklich Mitglied
"""

import uuid

from app.models import Household, HouseholdMember, User
from tests.pg.harness import auth_headers, run_parallel, status_codes

ROUNDS = 6


def _members(db, household_id):
    db.expire_all()
    return db.query(HouseholdMember).filter_by(household_id=household_id).all()


def _household_exists(db, household_id) -> bool:
    db.expire_all()
    return db.get(Household, household_id) is not None


def _invite_code(db, household_id) -> str:
    db.expire_all()
    return db.get(Household, household_id).invite_code


def _new_user(db, name: str) -> tuple[uuid.UUID, str]:
    from app.core.security import create_access_token

    u = User(
        id=uuid.uuid4(),
        email=f"{name.lower()}-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        display_name=name,
    )
    db.add(u)
    db.commit()
    return u.id, create_access_token(str(u.id))


def _parallel_leaves(client, hh, indices):
    return status_codes(
        run_parallel(lambda i: client.post(hh.url("/leave"), headers=hh.headers(indices[i])), len(indices))
    )


def _join(client, code, token):
    return client.post("/api/households/join", json={"invite_code": code}, headers=auth_headers(token))


def test_admin_and_senior_leave_concurrently_keeps_an_admin(client, db, make_household):
    for _ in range(ROUNDS):
        hh = make_household(["Anna", "Ben", "Carla"])  # Anna Admin, Ben dienstältester Member

        assert _parallel_leaves(client, hh, [0, 1]) == [204, 204]
        members = _members(db, hh.id)
        assert [m.user_id for m in members] == [hh.user_ids[2]]
        assert members[0].role == "admin"


def test_last_two_members_leave_concurrently_deletes_household(client, db, make_household):
    for _ in range(ROUNDS):
        hh = make_household(["Anna", "Ben"])
        assert _parallel_leaves(client, hh, [0, 1]) == [204, 204]
        assert not _household_exists(db, hh.id)


def _join_vs_last_leave(client, db, hh, n):
    code = _invite_code(db, hh.id)
    joiner_id, joiner_token = _new_user(db, f"Joiner{n}")

    def act(i):
        if i == 0:
            return client.post(hh.url("/leave"), headers=hh.headers(0))
        return _join(client, code, joiner_token)

    leave, join = run_parallel(act, 2)
    assert leave.status_code == 204
    assert join.status_code in (200, 404), join.text
    if join.status_code == 200:
        # Join kam zuerst: Haushalt lebt weiter, der Neue ist (einziger) Admin
        members = _members(db, hh.id)
        assert [m.user_id for m in members] == [joiner_id]
        assert members[0].role == "admin"
    else:
        assert not _household_exists(db, hh.id)


def test_join_racing_last_leave_never_reports_phantom_membership(client, db, make_household):
    for n in range(ROUNDS):
        _join_vs_last_leave(client, db, make_household(["Anna"]), n)


def _double_join(client, db, hh, n):
    code = _invite_code(db, hh.id)
    _, joiner_token = _new_user(db, f"Twice{n}")
    codes = sorted(status_codes(run_parallel(lambda i: _join(client, code, joiner_token), 2)))
    assert codes == [200, 409]
    assert len(_members(db, hh.id)) == 2


def test_double_join_one_success_one_already_member(client, db, make_household):
    for n in range(ROUNDS):
        _double_join(client, db, make_household(["Anna"]), n)


def _remove_vs_leave(client, db, hh):
    target = hh.user_ids[1]

    def act(i):
        if i == 0:
            return client.delete(hh.url(f"/members/{target}"), headers=hh.headers(0))
        return client.post(hh.url("/leave"), headers=hh.headers(1))

    codes = status_codes(run_parallel(act, 2))
    assert 500 not in codes
    # Einer gewinnt (204), der andere sieht die Mitgliedschaft nicht mehr
    assert sorted(codes) in ([204, 204], [204, 403], [204, 404])
    members = _members(db, hh.id)
    assert target not in {m.user_id for m in members}
    assert any(m.role == "admin" for m in members)


def test_remove_racing_leave_of_same_member_no_500(client, db, make_household):
    for _ in range(ROUNDS):
        _remove_vs_leave(client, db, make_household(["Anna", "Ben", "Carla"]))
