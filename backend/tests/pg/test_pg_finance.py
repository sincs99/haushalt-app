"""Finanzen auf PostgreSQL: Nebenläufigkeit (CASA-01/03/08) und Migration fin1a2b3c4d5.

Invariante nach jedem Lauf: Σ Anteile == Betrag für jede Ausgabe; die Salden aller
Personen summieren sich (ohne Ausgaben ohne Zahler) zu 0.
"""

import uuid

from sqlalchemy import create_engine, text

from app.models import Expense, Settlement
from tests.pg.harness import fresh_database, run_alembic, run_parallel, status_codes

ROUNDS = 6


def _create_expense(client, hh, amount=1000, participants=None, payer=0):
    body = {
        "description": "Einkauf",
        "amount_rappen": amount,
        "paid_by_user_id": str(hh.user_ids[payer]),
        "split_type": "even",
        "participant_ids": [str(u) for u in (participants or hh.user_ids)],
    }
    resp = client.post(hh.url("/expenses/"), json=body, headers=hh.headers(0))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _assert_ledger_consistent(client, hh, db):
    db.expire_all()
    rows = db.execute(
        text(
            "SELECT e.id, e.amount_rappen, COALESCE(SUM(s.amount_rappen), 0), COUNT(s.id) "
            "FROM expenses e LEFT JOIN expense_shares s ON s.expense_id = e.id "
            "WHERE e.household_id = :h GROUP BY e.id"
        ),
        {"h": hh.id},
    ).all()
    for eid, amount, share_sum, n in rows:
        assert share_sum == amount, f"expense {eid}: Σshares {share_sum} != amount {amount}"
        assert n >= 1
    balances = client.get(hh.url("/expenses/balances"), headers=hh.headers(0)).json()
    total = sum(b["saldo_rappen"] for b in balances["balances"])
    assert total == -balances["unassigned_rappen"]


def test_parallel_patch_disjoint_participants_keeps_shares_consistent(client, make_household, db):
    """CASA-01: PATCH ‖ PATCH mit disjunkten Teilnehmern ergab 4 Anteile (Σ = 2× Betrag)."""
    hh = make_household(["Anna", "Ben", "Carla", "Dora"])
    for _ in range(ROUNDS):
        exp = _create_expense(client, hh)
        groups = [hh.user_ids[:2], hh.user_ids[2:]]

        def patch(i, exp=exp, groups=groups):
            return client.patch(
                hh.url(f"/expenses/{exp['id']}"),
                json={"participant_ids": [str(u) for u in groups[i]]},
                headers=hh.headers(i),
            )

        codes = status_codes(run_parallel(patch, 2))
        assert set(codes) <= {200, 409}, codes
        _assert_ledger_consistent(client, hh, db)
        final = client.get(hh.url(f"/expenses/{exp['id']}"), headers=hh.headers(0)).json()
        assert len(final["shares"]) == 2
        assert final["version"] == 1 + codes.count(200)


def test_parallel_patch_amount_and_participants_never_500(client, make_household, db):
    """CASA-01: Betrag ‖ Teilnehmer (überlappend) lief in uq_expense_share_user → 500."""
    hh = make_household(["Anna", "Ben", "Carla"])
    for r in range(ROUNDS):
        exp = _create_expense(client, hh)

        def patch(i, exp=exp, r=r):
            body = (
                {"amount_rappen": 2000 + r}
                if i == 0
                else {"participant_ids": [str(u) for u in hh.user_ids[:2]]}
            )
            return client.patch(hh.url(f"/expenses/{exp['id']}"), json=body, headers=hh.headers(i))

        codes = status_codes(run_parallel(patch, 2))
        assert set(codes) <= {200, 409}, codes
        _assert_ledger_consistent(client, hh, db)


def test_parallel_delete_and_patch(client, make_household, db):
    """CASA-01: DELETE ‖ PATCH ergab Deadlock/StaleDataError → 500."""
    hh = make_household(["Anna", "Ben", "Carla"])
    for _ in range(ROUNDS):
        exp = _create_expense(client, hh)

        def act(i, exp=exp):
            url = hh.url(f"/expenses/{exp['id']}")
            if i == 0:
                return client.delete(url, headers=hh.headers(0))
            return client.patch(url, json={"participant_ids": [str(hh.user_ids[1])]}, headers=hh.headers(1))

        codes = status_codes(run_parallel(act, 2))
        assert codes[0] == 204, codes
        assert codes[1] in (200, 409), codes
        _assert_ledger_consistent(client, hh, db)
        db.expire_all()
        assert db.get(Expense, uuid.UUID(exp["id"])).deleted_at is not None


def test_parallel_patch_same_version_one_wins(client, make_household, db):
    """PD-F7: Zwei Dialoge mit derselben Version → genau einer speichert, der andere 409."""
    hh = make_household(["Anna", "Ben", "Carla"])
    for r in range(ROUNDS):
        exp = _create_expense(client, hh)

        def patch(i, exp=exp, r=r):
            return client.patch(
                hh.url(f"/expenses/{exp['id']}"),
                json={"amount_rappen": 3000 + 10 * r + i},
                headers={**hh.headers(i), "If-Match": str(exp["version"])},
            )

        results = run_parallel(patch, 2)
        codes = sorted(status_codes(results))
        assert codes == [200, 409], codes
        loser = next(x for x in results if x.status_code == 409)
        assert loser.json()["detail"]["code"] == "EXPENSE_VERSION_CONFLICT"
        _assert_ledger_consistent(client, hh, db)


def test_parallel_settlement_same_client_id_creates_one(client, household, db):
    """CASA-08: Retry/Doppelklick mit gleicher Client-ID → genau ein Ausgleich."""
    _create_expense(client, household, amount=5000)
    sid = str(uuid.uuid4())

    def post(i):
        return client.post(
            household.url("/settlements/"),
            json={"id": sid, "from_user_id": str(household.user_ids[1]),
                  "to_user_id": str(household.user_ids[0]), "amount_rappen": 2500},
            headers=household.headers(i % 2),
        )

    codes = status_codes(run_parallel(post, 4))
    assert sorted(codes) == [200, 200, 200, 201], codes
    db.expire_all()
    assert db.query(Settlement).filter_by(household_id=household.id).count() == 1


def test_parallel_settlement_both_parties_second_is_flagged(client, household, db):
    """CASA-08: Schuldner und Gläubiger erfassen dieselbe Zahlung gleichzeitig — beide
    gespeichert (warnen, nicht ablehnen), aber der zweite trägt DUPLICATE_RECENT."""
    _create_expense(client, household, amount=5000)

    def post(i):
        return client.post(
            household.url("/settlements/"),
            json={"id": str(uuid.uuid4()), "from_user_id": str(household.user_ids[1]),
                  "to_user_id": str(household.user_ids[0]), "amount_rappen": 2500},
            headers=household.headers(i),
        )

    results = run_parallel(post, 2)
    assert status_codes(results) == [201, 201]
    flagged = [r for r in results if "DUPLICATE_RECENT" in r.json()["warnings"]]
    assert len(flagged) == 1


def test_parallel_restore_and_rebook_never_double_books(client, household, db):
    """CASA-03: Wiederherstellen ‖ Neubuchen desselben Monats → höchstens eine aktive Buchung."""
    bill = client.post(
        household.url("/recurring-bills/"),
        json={"name": "Miete", "amount_rappen": 300000, "day_of_month": 1,
              "paid_by_user_id": str(household.user_ids[0])},
        headers=household.headers(0),
    ).json()
    for _ in range(ROUNDS):
        booked = client.post(household.url(f"/recurring-bills/{bill['id']}/book"), headers=household.headers(0))
        assert booked.status_code == 201, booked.text
        exp_id = booked.json()["id"]
        assert client.delete(household.url(f"/expenses/{exp_id}"), headers=household.headers(0)).status_code == 204

        def act(i, exp_id=exp_id):
            if i == 0:
                return client.post(household.url(f"/expenses/{exp_id}/restore"), headers=household.headers(0))
            return client.post(household.url(f"/recurring-bills/{bill['id']}/book"), headers=household.headers(1))

        codes = status_codes(run_parallel(act, 2))
        assert 500 not in codes, codes
        assert sorted(codes) in ([200, 409], [201, 409]), codes
        db.expire_all()
        active = (
            db.query(Expense)
            .filter(Expense.recurring_bill_id == uuid.UUID(bill["id"]), Expense.deleted_at.is_(None))
            .all()
        )
        assert len(active) == 1
        # Für die nächste Runde wieder freigeben
        client.delete(household.url(f"/expenses/{active[0].id}"), headers=household.headers(0))


# ---------------------------------------------------------------------------
# Migration fin1a2b3c4d5
# ---------------------------------------------------------------------------


def test_finance_migration_upgrade_and_downgrade(pg_admin_url):
    with fresh_database(pg_admin_url, upgrade_to="fnd1a2b3c4d5") as url:
        engine = create_engine(url)
        try:
            hid, uid, bill, e1 = (uuid.uuid4() for _ in range(4))
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO households (id, name, invite_code, timezone, currency, created_at) "
                    "VALUES (:h, 'HH', :code, 'Europe/Zurich', 'CHF', now())"
                ), {"h": hid, "code": uuid.uuid4().hex[:8].upper()})
                conn.execute(text(
                    "INSERT INTO users (id, email, password_hash, display_name, created_at) "
                    "VALUES (:u, :e, 'x', 'A', now())"
                ), {"u": uid, "e": f"{uid.hex[:8]}@example.com"})
                conn.execute(text(
                    "INSERT INTO recurring_bills (id, household_id, name, amount_rappen, day_of_month, "
                    "split_type, active, created_at) VALUES (:b, :h, 'Miete', 1000, 1, 'custom', true, now())"
                ), {"b": bill, "h": hid})
                conn.execute(text(
                    "INSERT INTO expenses (id, household_id, description, amount_rappen, split_type, paid_by_user_id, "
                    "recurring_bill_id, booked_month, expense_date, created_at, updated_at) "
                    "VALUES (:e, :h, 'Miete', 1000, 'even', :u, :b, '2026-09-01', '2026-09-01', now(), now())"
                ), {"e": e1, "h": hid, "u": uid, "b": bill})

            run_alembic(url, "upgrade", "fin1a2b3c4d5")
            with engine.begin() as conn:
                assert conn.execute(text("SELECT split_type FROM recurring_bills")).scalar_one() == "even"
                assert conn.execute(text("SELECT version FROM expenses")).scalar_one() == 1
                # Gelöschte Buchung gibt den Monat frei (partieller Unique-Index)
                conn.execute(text("UPDATE expenses SET deleted_at = now() WHERE id = :e"), {"e": e1})
                conn.execute(text(
                    "INSERT INTO expenses (id, household_id, description, amount_rappen, split_type, "
                    "recurring_bill_id, booked_month, expense_date, created_at, updated_at) "
                    "VALUES (:e, :h, 'Miete', 1000, 'even', :b, '2026-09-01', '2026-09-01', now(), now())"
                ), {"e": uuid.uuid4(), "h": hid, "b": bill})

            # Rückweg: gelöschte Zeilen verschwinden, Unique-Constraint kommt zurück
            run_alembic(url, "downgrade", "-1")
            with engine.connect() as conn:
                assert conn.execute(text("SELECT count(*) FROM expenses")).scalar_one() == 1
            run_alembic(url, "upgrade", "head")
        finally:
            engine.dispose()
