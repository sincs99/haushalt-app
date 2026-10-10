"""Smoke-Tests der PostgreSQL-Lane: Migrationen, Schema-Drift, Parallelität."""

import re
import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.pg.harness import run_parallel, status_codes


def test_migrations_applied_to_head(pg_url, db):
    """Die Lane-DB steht auf genau einem Alembic-Head und enthält die Kerntabellen."""
    heads = db.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    assert len(heads) == 1
    tables = set(
        db.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        ).scalars()
    )
    assert {"households", "users", "household_members", "expenses", "events"} <= tables


def _normalize_default(value):
    """``'de'::character varying`` → ``de``, ``now()`` → ``now()``, ``'0'`` → ``0``."""
    if value is None:
        return None
    value = re.sub(r"::[\w ]+(\[\])?", "", str(value))
    return value.replace("'", "").replace('"', "").strip().lower()


def _compare_server_default(context, insp_col, meta_col, insp_def, meta_def, rendered_meta_def):
    """True = Unterschied. Vergleicht Vorhandensein und normalisierten Text (CASA-56).

    Alembics eingebauter PG-Vergleich führt SQL aus und scheitert an JSON-Defaults.
    """
    return _normalize_default(insp_def) != _normalize_default(rendered_meta_def)


def _flatten(diffs):
    """modify_*-Diffs kommen als Liste von Tupeln pro Spalte."""
    out = []
    for d in diffs:
        out.extend(d if isinstance(d, list) else [d])
    return out


def test_models_match_migrations(pg_url):
    """Drift-Check: Base.metadata (Modelle) vs. per Alembic migrierte DB.

    Inklusive Nullability und Server-Defaults (CASA-56): jeder DB-Default hat ein
    Modell-Pendant, damit ``create_all`` (SQLite-Lane) und Migrationen dasselbe Schema bauen.
    """
    import app.models  # noqa: F401 — registriert alle Tabellen
    from app.database import Base

    engine = create_engine(pg_url)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(
                conn,
                opts={"compare_type": True, "compare_server_default": _compare_server_default},
            )
            diffs = _flatten(compare_metadata(ctx, Base.metadata))
    finally:
        engine.dispose()
    assert diffs == [], "Schema-Drift zwischen Modellen und Migrationen:\n" + "\n".join(map(str, diffs))


# Ledger-FKs auf users (PD-D1 / CASA-55): eine Löschung der Person darf Buchungen weder
# mitlöschen (CASCADE → Salden der anderen ändern sich) noch den Zahler leeren (SET NULL).
LEDGER_USER_FKS = {
    ("expense_shares", "user_id"): "RESTRICT",
    ("settlements", "from_user_id"): "RESTRICT",
    ("settlements", "to_user_id"): "RESTRICT",
    ("expenses", "paid_by_user_id"): "RESTRICT",
}


def test_ledger_user_fks_restrict(db):
    rows = db.execute(text(
        "SELECT c.conrelid::regclass::text, a.attname, c.confdeltype "
        "FROM pg_constraint c JOIN pg_attribute a "
        "  ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey) "
        "WHERE c.contype = 'f' AND c.confrelid = 'users'::regclass"
    )).all()
    names = {"r": "RESTRICT", "c": "CASCADE", "n": "SET NULL", "a": "NO ACTION", "d": "SET DEFAULT"}
    actual = {(t, col): names[rule] for t, col, rule in rows}
    for key, rule in LEDGER_USER_FKS.items():
        assert actual.get(key) == rule, (key, actual.get(key))


def test_deleting_user_with_ledger_rows_is_blocked(db, make_household):
    """Ein User mit Ausgabenanteil lässt sich auf DB-Ebene nicht löschen (keine stille Saldo-Änderung)."""
    from app.models import Expense, ExpenseShare

    hh = make_household(["Anna", "Ben"])
    expense = Expense(
        household_id=hh.id, description="Test", amount_rappen=1000, paid_by_user_id=hh.user_ids[0]
    )
    expense.shares = [
        ExpenseShare(household_id=hh.id, user_id=uid, amount_rappen=500) for uid in hh.user_ids
    ]
    db.add(expense)
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(text("DELETE FROM household_members WHERE user_id = :u"), {"u": hh.user_ids[1]})
        db.execute(text("DELETE FROM users WHERE id = :u"), {"u": hh.user_ids[1]})
    db.rollback()


def test_parallel_requests_use_real_sessions(client, household, emits):
    """Parallele Requests laufen auf eigenen Sessions und kommen alle durch."""

    def create(i):
        return client.post(
            household.url("/todos/"),
            json={"title": f"Parallel {i}", "id": str(uuid.uuid4())},
            headers=household.headers(i % 2),
        )

    results = run_parallel(create, 8)
    assert status_codes(results) == [201] * 8

    listed = client.get(household.url("/todos/"), headers=household.headers()).json()
    assert len(listed) == 8
    assert len(emits.events("todo_created")) == 8
