"""F0-2: Sperr-Helfer (SQLite: No-Op-sicher) und globales DB-Konflikt-Mapping → 409.

Die echten Race-Tests laufen in der PostgreSQL-Lane (tests/pg/test_pg_conflicts.py).
"""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError

from app.core.db_errors import install_db_error_handlers, is_retryable_db_error
from app.core.error_codes import ErrorCode
from app.database import get_db
from app.main import app as main_app
from app.models import Household, Todo
from app.services.locking import lock_household, lock_row


class _PgError(Exception):
    """Simuliert psycopg2-Fehler mit SQLSTATE."""

    def __init__(self, pgcode: str):
        super().__init__(f"pgcode {pgcode}")
        self.pgcode = pgcode


def _operational(pgcode: str) -> OperationalError:
    return OperationalError("UPDATE …", {}, _PgError(pgcode))


@pytest.fixture()
def conflict_app():
    test_app = FastAPI()
    install_db_error_handlers(test_app)
    errors = {
        "integrity": IntegrityError("INSERT …", {}, Exception("duplicate key")),
        "stale": StaleDataError("UPDATE statement on table 'x' expected to update 1 row(s); 0 were matched."),
        "deadlock": _operational("40P01"),
        "serialization": _operational("40001"),
        "lock_timeout": _operational("55P03"),
        "connection": _operational("08006"),
    }

    @test_app.get("/raise/{kind}")
    def _raise(kind: str):
        raise errors[kind]

    return TestClient(test_app, raise_server_exceptions=False)


@pytest.mark.parametrize("kind", ["integrity", "stale", "deadlock", "serialization", "lock_timeout"])
def test_db_conflicts_map_to_409(conflict_app, kind):
    r = conflict_app.get(f"/raise/{kind}")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == ErrorCode.CONFLICT_RETRY


def test_other_operational_errors_stay_500(conflict_app):
    r = conflict_app.get("/raise/connection")
    assert r.status_code == 500


def test_is_retryable_db_error():
    assert is_retryable_db_error(_operational("40P01"))
    assert not is_retryable_db_error(_operational("08006"))
    assert not is_retryable_db_error(OperationalError("x", {}, Exception("no pgcode")))


def test_main_app_installs_handlers():
    for exc in (IntegrityError, StaleDataError, OperationalError):
        assert exc in main_app.exception_handlers


def test_get_db_rolls_back_on_exception(db, household_a, user_a, monkeypatch):
    """Eine im Endpoint geworfene Exception rollt die Request-Session explizit zurück."""
    import app.database as database

    class _KeepOpen:
        """Session-Proxy ohne close() — sonst würde close() das Rollback verdecken."""

        def __getattr__(self, name):
            return getattr(db, name)

        def close(self):
            pass

    monkeypatch.setattr(database, "SessionLocal", _KeepOpen)
    gen = get_db()
    session = next(gen)
    session.add(Todo(id=uuid.uuid4(), household_id=household_a.id, title="nie committet",
                     created_by_user_id=user_a.id))
    session.flush()
    with pytest.raises(RuntimeError):
        gen.throw(RuntimeError("boom"))
    assert db.query(Todo).filter_by(title="nie committet").count() == 0


def test_lock_helpers_on_sqlite(db, household_a, todo_a):
    """Auf SQLite ist FOR UPDATE ein No-Op — die Helfer liefern trotzdem die Zeile."""
    assert lock_household(db, household_a.id).id == household_a.id
    assert lock_household(db, uuid.uuid4()) is None
    assert lock_row(db, Todo, todo_a.id).id == todo_a.id
    assert lock_row(db, Todo, uuid.uuid4()) is None
    assert isinstance(lock_row(db, Household, household_a.id), Household)
