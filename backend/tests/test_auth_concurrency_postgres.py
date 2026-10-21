"""Opt-in PostgreSQL regression for refresh/logout serialization.

Run only in an isolated test environment with TEST_AUTH_POSTGRES_URL pointing at
a disposable loopback database whose name starts with test_. SQLite cannot prove
row-lock behavior. Every run owns a fresh schema, never existing application data.
"""

import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.security import hash_refresh_token
from app.database import Base
from app.models import RefreshToken, User
from app.routers import auth


@pytest.fixture()
def postgres_sessions():
    raw_url = os.environ.get("TEST_AUTH_POSTGRES_URL")
    if not raw_url:
        pytest.skip("requires isolated PostgreSQL via TEST_AUTH_POSTGRES_URL")
    url = make_url(raw_url)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not (url.database or "").startswith("test_")
    ):
        pytest.fail("TEST_AUTH_POSTGRES_URL must name a loopback PostgreSQL test_* database")
    schema = "auth_regression_" + uuid.uuid4().hex
    engine = create_engine(url, isolation_level="READ COMMITTED", connect_args={"connect_timeout": 5})
    scoped = engine.execution_options(schema_translate_map={None: schema})
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        Base.metadata.create_all(scoped, tables=[User.__table__, RefreshToken.__table__])
        yield sessionmaker(bind=scoped, autoflush=False), engine
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/api/auth/refresh", "headers": []})


def _call(operation, raw_token, db):
    if operation == "logout":
        auth.logout_endpoint(_request(), Response(), auth.LogoutRequest(refresh_token=raw_token), db)
        return 204
    try:
        return auth.refresh_endpoint(_request(), Response(), auth.RefreshRequest(refresh_token=raw_token), db)
    except HTTPException as error:
        db.rollback()
        return error.status_code


@pytest.mark.parametrize("first_operation,grace", [("refresh", False), ("logout", False), ("refresh", True)])
def test_refresh_and_logout_serialize_even_when_using_different_chain_links(
    postgres_sessions, first_operation, grace
):
    sessions, engine = postgres_sessions
    user_id = uuid.uuid4()
    token_a, token_b = "dummy-a-" + uuid.uuid4().hex, "dummy-b-" + uuid.uuid4().hex
    with sessions() as db:
        db.add(User(id=user_id, email=f"{user_id}@example.test", password_hash="unused", display_name="Dummy"))
        db.flush()
        ancestor = RefreshToken(user_id=user_id, token_hash=hash_refresh_token(token_a), expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        db.add(ancestor)
        if grace:
            successor = RefreshToken(user_id=user_id, token_hash=hash_refresh_token(token_b), expires_at=ancestor.expires_at)
            db.add(successor)
            db.flush()
            ancestor.revoked_at = datetime.now(timezone.utc)
            ancestor.replaced_by_id = successor.id
        db.commit()

    locked, release, competing = threading.Event(), threading.Event(), threading.Event()
    competitor_pid: list[int] = []
    actual_lock = auth._lock_refresh_owner

    def controlled_lock(token_hash, db):
        if db.info["first"]:
            row = actual_lock(token_hash, db)
            locked.set()
            assert release.wait(10), "test did not release first transaction"
            return row
        competitor_pid.append(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
        competing.set()
        return actual_lock(token_hash, db)

    def worker(first):
        operation = first_operation if first else ("logout" if first_operation == "refresh" else "refresh")
        raw = token_b if grace and operation == "logout" else token_a
        with sessions() as db:
            db.info["first"] = first
            db.execute(text("SET LOCAL lock_timeout = '8s'"))
            return _call(operation, raw, db)

    with patch.object(auth, "_lock_refresh_owner", controlled_lock), patch.object(auth, "disconnect_user_sync"):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(worker, True)
            try:
                assert locked.wait(5)
                second = pool.submit(worker, False)
                assert competing.wait(5)
                # Observe a real PostgreSQL lock wait, not just thread timing.
                deadline = time.monotonic() + 5
                blocked = False
                while time.monotonic() < deadline:
                    with engine.connect() as observer:
                        blocked = observer.execute(text(
                            "SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"
                        ), {"pid": competitor_pid[0]}).scalar()
                    if blocked:
                        break
                    time.sleep(0.01)
                assert blocked, "competing auth request did not wait for the owner lock"
            finally:
                release.set()
            results = [first.result(timeout=10), second.result(timeout=10)]

    with sessions() as db:
        assert db.query(RefreshToken).filter_by(user_id=user_id, revoked_at=None).count() == 0
        if first_operation == "logout":
            assert results == [204, 401]
        else:
            assert isinstance(results[0], auth.TokenResponse)
            assert results[1] == 204
            # The issued successor cannot renew after the racing logout completed.
            assert _call("refresh", results[0].refresh_token, db) == 401
