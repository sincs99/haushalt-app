"""Opt-in PostgreSQL contention regressions. Never use the application's DB URL.

Set SECURITY_TEST_DATABASE_URL to a disposable local database named *_test or
test_*. Each test owns a random schema; no existing schema or data is modified.
This module performs no provider calls. SQLite cannot prove these lock tests.
"""

import io
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import Column, Integer, MetaData, Table, UniqueConstraint, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers

from app.core.config import settings
from app.database import Base
from app.models import AiBudgetCounter, AiUsage, Household, StoredFile, User
from app.routers import files
from app.services.ai import usage
from app.services.ai.errors import AiDailyLimitReached
from app.services.storage import LocalStorageService


@pytest.fixture
def pg_sessions():
    raw_url = os.environ.get("SECURITY_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("Requires explicit disposable SECURITY_TEST_DATABASE_URL")
    url = make_url(raw_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not ((url.database or "").startswith("test_") or (url.database or "").endswith("_test"))
    ):
        pytest.fail("Security contention tests require an explicitly named local test database")
    schema = "audit_fixture_" + uuid.uuid4().hex
    engine = create_engine(url, connect_args={"options": "-c statement_timeout=5000 -c lock_timeout=4000"})
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = engine.execution_options(schema_translate_map={None: schema})
    sessions = sessionmaker(bind=isolated, autoflush=False, expire_on_commit=False)
    try:
        Base.metadata.create_all(isolated)
        with sessions() as db:
            user = User(id=uuid.uuid4(), email="fixture@example.invalid", password_hash="fixture", display_name="Fixture")
            households = [Household(id=uuid.uuid4(), name=f"Fixture {i}", invite_code=uuid.uuid4().hex[:8]) for i in range(2)]
            db.add_all([user, *households])
            db.commit()
        yield sessions, engine, user.id, [household.id for household in households]
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_postgres_upload_waits_then_rechecks_committed_quota(pg_sessions, tmp_path, monkeypatch):
    sessions, engine, user_id, household_ids = pg_sessions
    household_id = household_ids[0]
    payload = b"%PDF-fixture"
    monkeypatch.setattr(files, "household_storage_quota", lambda: len(payload))
    monkeypatch.setattr(files, "_storage", LocalStorageService(str(tmp_path)))
    first_saved, release_first, second_started = threading.Event(), threading.Event(), threading.Event()
    second_pid = []

    def upload(first):
        with sessions() as db:
            if not first:
                second_pid.append(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
                second_started.set()
            try:
                with files.upload_transaction(db):
                    files.store_upload(db, household_id, user_id, UploadFile(
                        file=io.BytesIO(payload), filename="fixture.pdf",
                        headers=Headers({"content-type": "application/pdf"}),
                    ))
                    if first:
                        first_saved.set()
                        assert release_first.wait(3)
                return 201
            except HTTPException as exc:
                assert exc.detail["code"] == "STORAGE_QUOTA_EXCEEDED"
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(upload, True)
        assert first_saved.wait(2)
        second = workers.submit(upload, False)
        try:
            assert second_started.wait(2)
            deadline = time.monotonic() + 2
            waiting = False
            while time.monotonic() < deadline:
                with engine.connect() as observer:
                    waiting = observer.execute(text(
                        "SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"
                    ), {"pid": second_pid[0]}).scalar_one()
                if waiting:
                    break
                time.sleep(0.01)
            assert waiting, "Second upload must wait for the first household transaction"
        finally:
            release_first.set()
        assert [first.result(timeout=4), second.result(timeout=4)] == [201, 422]
    with sessions() as db:
        assert db.query(StoredFile).count() == 1
        assert files.household_storage_used(db, household_id) == len(payload)
    assert len([path for path in tmp_path.rglob("*") if path.is_file()]) == 1


def test_postgres_commit_failure_removes_uploaded_batch(pg_sessions, tmp_path, monkeypatch):
    sessions, _, user_id, household_ids = pg_sessions
    monkeypatch.setattr(files, "_storage", LocalStorageService(str(tmp_path)))
    guard = Table(
        "upload_commit_guard", MetaData(), Column("value", Integer),
        UniqueConstraint("value", deferrable=True, initially="DEFERRED"),
    )
    with sessions() as db:
        guard.create(db.get_bind())
        with pytest.raises(IntegrityError):
            with files.upload_transaction(db):
                for _ in range(2):
                    files.store_upload(db, household_ids[0], user_id, UploadFile(
                        file=io.BytesIO(b"%PDF-fixture"), filename="fixture.pdf",
                        headers=Headers({"content-type": "application/pdf"}),
                    ))
                # Both uploads have flushed; this constraint fails at COMMIT.
                db.execute(guard.insert(), [{"value": 1}, {"value": 1}])
        assert db.query(StoredFile).count() == 0
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


def test_postgres_flush_failure_removes_current_and_prior_blob(pg_sessions, tmp_path, monkeypatch):
    sessions, _, user_id, household_ids = pg_sessions
    monkeypatch.setattr(files, "_storage", LocalStorageService(str(tmp_path)))
    with sessions() as db:
        with pytest.raises(IntegrityError):
            with files.upload_transaction(db):
                for uploader in (user_id, uuid.uuid4()):
                    files.store_upload(db, household_ids[0], uploader, UploadFile(
                        file=io.BytesIO(b"%PDF-fixture"), filename="fixture.pdf",
                        headers=Headers({"content-type": "application/pdf"}),
                    ))
        assert db.query(StoredFile).count() == 0
    assert not any(path.is_file() for path in tmp_path.rglob("*"))


@pytest.mark.parametrize("limit_scope", ["ai_daily_limit_per_user", "ai_daily_limit_global"])
def test_postgres_concurrent_new_counter_reservations_are_atomic(pg_sessions, monkeypatch, limit_scope):
    sessions, _, user_id, household_ids = pg_sessions
    monkeypatch.setattr(settings, limit_scope, 1)
    ready = threading.Barrier(2)

    def reserve(household_id):
        with sessions() as db:
            ready.wait(timeout=3)
            try:
                return usage.reserve_call(db, household_id, user_id)
            except AiDailyLimitReached:
                return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(reserve, household_ids))
    assert sum(result is not None for result in results) == 1
    with sessions() as db:
        assert db.query(AiBudgetCounter).filter_by(scope_key="global").one().calls == 1
        assert db.query(AiBudgetCounter).filter_by(scope_key=f"user:{user_id}").one().calls == 1
        assert sum(row.calls for row in db.query(AiUsage).all()) == 1


def test_postgres_duplicate_refunds_do_not_consume_another_reservation(pg_sessions):
    sessions, _, user_id, household_ids = pg_sessions
    with sessions() as db:
        first = usage.reserve_call(db, household_ids[0], user_id)
        usage.reserve_call(db, household_ids[0], user_id)
    ready = threading.Barrier(2)

    def release(_):
        with sessions() as db:
            ready.wait(timeout=3)
            usage.release_call(db, first)

    with ThreadPoolExecutor(max_workers=2) as workers:
        list(workers.map(release, range(2)))
    with sessions() as db:
        assert db.query(AiBudgetCounter).filter_by(scope_key="global").one().calls == 1
        assert db.query(AiUsage).one().calls == 1
