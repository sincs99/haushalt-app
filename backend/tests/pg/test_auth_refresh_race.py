"""Gleichzeitiger Token-Refresh (CASA-11) auf echtem PostgreSQL.

Zwei oder drei Requests mit demselben Refresh-Token (Tabs, die gleichzeitig aufwachen,
PWA + Tab) dürfen nie die Reuse-Detection auslösen und nie zwei aktive Ketten erzeugen.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import create_refresh_token, hash_refresh_token
from app.models import RefreshToken
from tests.pg.harness import run_parallel

ROUNDS = 8


def _issue_refresh_token(db, user_id: uuid.UUID) -> str:
    raw = create_refresh_token()
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hash_refresh_token(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
    )
    db.commit()
    return raw


def _active_tokens(db, user_id):
    db.expire_all()
    return db.query(RefreshToken).filter(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)).all()


def _round(client, db, user_id, n):
    raw = _issue_refresh_token(db, user_id)
    results = run_parallel(lambda i: client.post("/api/auth/refresh", json={"refresh_token": raw}), n)
    bodies = [r.json() for r in results]
    assert [r.status_code for r in results] == [200] * n, bodies
    # Genau eine aktive Kette: ein aktiver Token für den User
    assert len(_active_tokens(db, user_id)) == 1


@pytest.mark.parametrize("n", [2, 3])
def test_concurrent_refresh_never_triggers_reuse_detection(client, db, make_household, n):
    for _ in range(ROUNDS):
        # Frischer User pro Runde: "genau ein aktiver Token" gilt pro Kette
        _round(client, db, make_household(["Anna"]).user_ids[0], n)


def test_third_use_within_grace_follows_replacement_chain(client, db, make_household):
    """Nacheinander: T0 → T1, dann T0 nochmal (→ T2), dann T0 ein drittes Mal (→ T3)."""
    user_id = make_household(["Anna"]).user_ids[0]
    raw = _issue_refresh_token(db, user_id)
    for _ in range(3):
        resp = client.post("/api/auth/refresh", json={"refresh_token": raw})
        assert resp.status_code == 200, resp.json()
    assert len(_active_tokens(db, user_id)) == 1
