"""Smoke-Tests der PostgreSQL-Lane: Migrationen, Schema-Drift, Parallelität."""

import uuid

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

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


def _structural_diffs(diffs):
    """Strukturelle Unterschiede inkl. Nullability (Tabellen, Spalten, Typen, FKs, Indizes …).

    Ignoriert wird nur Server-Default-Drift (CASA-56: DB-seitige Defaults ohne
    Modell-Pendant) — die verändert kein Verhalten der App.
    """
    out = []
    for d in diffs:
        # modify_*-Diffs kommen als Liste von Tupeln pro Spalte
        if isinstance(d, list):
            out.extend(x for x in d if x[0] != "modify_default")
        else:
            out.append(d)
    return out


def test_models_match_migrations(pg_url):
    """Drift-Check: Base.metadata (Modelle) vs. per Alembic migrierte DB."""
    import app.models  # noqa: F401 — registriert alle Tabellen
    from app.database import Base

    engine = create_engine(pg_url)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": True})
            diffs = compare_metadata(ctx, Base.metadata)
    finally:
        engine.dispose()
    structural = _structural_diffs(diffs)
    assert structural == [], "Schema-Drift zwischen Modellen und Migrationen:\n" + "\n".join(
        map(str, structural)
    )


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
