"""Tests: Konto-Funktionen (Passwort vergessen/zurücksetzen, E-Mail bestätigen, Passwort ändern, Konto löschen)."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.models import (
    Expense,
    ExpenseShare,
    Household,
    HouseholdMember,
    RefreshToken,
    User,
    UserToken,
)
from app.services.account_tokens import (
    PURPOSE_EMAIL_VERIFICATION,
    PURPOSE_PASSWORD_RESET,
    issue_token,
)
from app.services.mail import Mail


@pytest.fixture()
def sent_mails(monkeypatch):
    """Console-Backend + Mitschnitt der verschickten Mails."""
    monkeypatch.setattr(settings, "mail_backend", "console")
    box: list[Mail] = []
    with patch("app.routers.account.send_mail", side_effect=lambda m: box.append(m) or True), patch(
        "app.services.mail.send_mail", side_effect=lambda m: box.append(m) or True
    ):
        yield box


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _token_from(mail: Mail) -> str:
    return mail.text.split("?token=", 1)[1].split()[0]


# ---------------------------------------------------------------------------
# Öffentliche Konfiguration
# ---------------------------------------------------------------------------


def test_public_config_reports_mail(client, monkeypatch):
    monkeypatch.setattr(settings, "mail_backend", "off")
    assert client.get("/api/config").json()["mail_enabled"] is False
    monkeypatch.setattr(settings, "mail_backend", "console")
    assert client.get("/api/config").json()["mail_enabled"] is True


def test_effective_mail_backend_auto(monkeypatch):
    monkeypatch.setattr(settings, "mail_backend", "auto")
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "environment", "development")
    assert settings.effective_mail_backend == "console"
    monkeypatch.setattr(settings, "environment", "production")
    assert settings.effective_mail_backend == "off"
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    assert settings.effective_mail_backend == "smtp"


# ---------------------------------------------------------------------------
# Passwort vergessen / zurücksetzen
# ---------------------------------------------------------------------------


def test_forgot_password_sends_mail_and_reset_works(client, db, user_a, sent_mails):
    resp = client.post("/api/account/password/forgot", json={"email": "alice@example.com"})
    assert resp.status_code == 202
    assert len(sent_mails) == 1
    assert sent_mails[0].to == "alice@example.com"
    assert "/reset-password?token=" in sent_mails[0].text
    token = _token_from(sent_mails[0])

    # Bestehende Sitzung (Refresh-Token) wird beim Reset widerrufen
    login = client.post("/api/auth/login", data={"username": "alice@example.com", "password": "password123"})
    old_refresh = login.json()["refresh_token"]

    resp = client.post("/api/account/password/reset", json={"token": token, "password": "newpassword9"})
    assert resp.status_code == 204

    # Altes Passwort ungültig, neues gilt
    assert client.post("/api/auth/login", data={"username": "alice@example.com", "password": "password123"}).status_code == 401
    assert client.post("/api/auth/login", data={"username": "alice@example.com", "password": "newpassword9"}).status_code == 200
    # Alter Refresh-Token ist widerrufen
    assert client.post("/api/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401
    # Token ist Einmal-Token
    resp = client.post("/api/account/password/reset", json={"token": token, "password": "another-pw1"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == ErrorCode.ACCOUNT_TOKEN_INVALID
    # Wer den Mail-Link öffnen konnte, besitzt das Postfach
    db.refresh(user_a)
    assert user_a.email_verified_at is not None


def test_forgot_password_unknown_email_is_silent(client, db, sent_mails):
    resp = client.post("/api/account/password/forgot", json={"email": "nobody@example.com"})
    assert resp.status_code == 202
    assert sent_mails == []


def test_forgot_password_english(client, db, user_a, sent_mails):
    client.post(
        "/api/account/password/forgot",
        json={"email": "alice@example.com"},
        headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    assert sent_mails[0].subject == "Reset your password"


def test_forgot_password_requires_mail(client, db, user_a, monkeypatch):
    monkeypatch.setattr(settings, "mail_backend", "off")
    resp = client.post("/api/account/password/forgot", json={"email": "alice@example.com"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == ErrorCode.MAIL_DISABLED


def test_reset_token_expired(client, db, user_a):
    raw = issue_token(db, user_a, PURPOSE_PASSWORD_RESET)
    db.commit()
    tok = db.query(UserToken).filter_by(user_id=user_a.id).one()
    tok.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    resp = client.post("/api/account/password/reset", json={"token": raw, "password": "newpassword9"})
    assert resp.status_code == 400


def test_newer_token_invalidates_older(client, db, user_a):
    first = issue_token(db, user_a, PURPOSE_PASSWORD_RESET)
    second = issue_token(db, user_a, PURPOSE_PASSWORD_RESET)
    db.commit()
    assert client.post("/api/account/password/reset", json={"token": first, "password": "newpassword9"}).status_code == 400
    assert client.post("/api/account/password/reset", json={"token": second, "password": "newpassword9"}).status_code == 204


def test_reset_password_too_short(client, db, user_a):
    raw = issue_token(db, user_a, PURPOSE_PASSWORD_RESET)
    db.commit()
    assert client.post("/api/account/password/reset", json={"token": raw, "password": "short"}).status_code == 422


# ---------------------------------------------------------------------------
# E-Mail-Bestätigung
# ---------------------------------------------------------------------------


def test_register_sends_verification_mail(client, db, sent_mails):
    resp = client.post("/api/auth/register", json={
        "email": "new@test.com",
        "password": "password123",
        "display_name": "Newbie",
        "household_name": "Mein Haushalt",
    })
    assert resp.status_code == 200
    assert len(sent_mails) == 1
    assert "/verify-email?token=" in sent_mails[0].text
    token = resp.json()["access_token"]
    assert client.get("/api/auth/me", headers=_auth(token)).json()["email_verified"] is False

    assert client.post("/api/account/email/verify", json={"token": _token_from(sent_mails[0])}).status_code == 204
    assert client.get("/api/auth/me", headers=_auth(token)).json()["email_verified"] is True

    # Erneut senden nach Bestätigung → 409
    resp = client.post("/api/account/email/resend", headers=_auth(token))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == ErrorCode.EMAIL_ALREADY_VERIFIED


def test_register_without_mail_backend_sends_nothing(client, db, monkeypatch):
    monkeypatch.setattr(settings, "mail_backend", "off")
    with patch("app.services.mail.send_mail") as send:
        resp = client.post("/api/auth/register", json={
            "email": "new@test.com",
            "password": "password123",
            "display_name": "Newbie",
            "household_name": "Mein Haushalt",
        })
    assert resp.status_code == 200
    send.assert_not_called()
    assert db.query(UserToken).count() == 0


def test_resend_verification(client, db, user_a, token_a, sent_mails):
    resp = client.post("/api/account/email/resend", headers=_auth(token_a))
    assert resp.status_code == 202
    assert len(sent_mails) == 1
    assert sent_mails[0].subject == "E-Mail-Adresse bestätigen"
    assert client.post("/api/account/email/verify", json={"token": _token_from(sent_mails[0])}).status_code == 204
    status = client.get("/api/account/status", headers=_auth(token_a)).json()
    assert status == {"mail_enabled": True, "email_verified": True}


def test_verify_token_wrong_purpose(client, db, user_a):
    raw = issue_token(db, user_a, PURPOSE_PASSWORD_RESET)
    db.commit()
    assert client.post("/api/account/email/verify", json={"token": raw}).status_code == 400
    raw = issue_token(db, user_a, PURPOSE_EMAIL_VERIFICATION)
    db.commit()
    assert client.post("/api/account/password/reset", json={"token": raw, "password": "newpassword9"}).status_code == 400


# ---------------------------------------------------------------------------
# Passwort ändern
# ---------------------------------------------------------------------------


def test_change_password(client, db, user_a, token_a, sent_mails):
    login = client.post("/api/auth/login", data={"username": "alice@example.com", "password": "password123"})
    old_refresh = login.json()["refresh_token"]

    resp = client.put(
        "/api/account/password",
        json={"current_password": "wrong", "new_password": "newpassword9"},
        headers=_auth(token_a),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == ErrorCode.PASSWORD_INCORRECT

    resp = client.put(
        "/api/account/password",
        json={"current_password": "password123", "new_password": "newpassword9"},
        headers=_auth(token_a),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    # Neues Paar gilt; andere Geräte sind abgemeldet (ihr Refresh-Token ist widerrufen)
    assert client.post("/api/auth/refresh", json={"refresh_token": body["refresh_token"]}).status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401
    assert client.post("/api/auth/login", data={"username": "alice@example.com", "password": "newpassword9"}).status_code == 200
    assert any(m.subject == "Dein Passwort wurde geändert" for m in sent_mails)


def test_change_password_web_client_gets_cookie(client, db, user_a, token_a):
    resp = client.put(
        "/api/account/password",
        json={"current_password": "password123", "new_password": "newpassword9"},
        headers={**_auth(token_a), "X-Requested-With": "casa"},
    )
    assert resp.status_code == 200
    assert resp.json()["refresh_token"] is None
    assert "casa_rt=" in resp.headers.get("set-cookie", "")


# ---------------------------------------------------------------------------
# Konto löschen
# ---------------------------------------------------------------------------


def test_delete_account_requires_password(client, db, user_a, token_a):
    resp = client.request("DELETE", "/api/account", json={"password": "nope"}, headers=_auth(token_a))
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == ErrorCode.PASSWORD_INCORRECT
    assert db.get(User, user_a.id).deleted_at is None


def test_delete_account_last_member_deletes_household(client, db, user_a, token_a, household_a):
    household_id = household_a.id
    user_id = user_a.id
    resp = client.request("DELETE", "/api/account", json={"password": "password123"}, headers=_auth(token_a))
    assert resp.status_code == 204

    assert db.get(Household, household_id) is None
    user = db.get(User, user_id)
    assert user.deleted_at is not None
    assert user.email == f"deleted-{user_id}@deleted.invalid"
    assert user.display_name == "Gelöschtes Konto"
    assert db.query(HouseholdMember).filter_by(user_id=user_id).count() == 0
    # Login und Token-Nutzung gesperrt
    assert client.post("/api/auth/login", data={"username": "alice@example.com", "password": "password123"}).status_code == 401
    assert client.get("/api/auth/me", headers=_auth(token_a)).status_code == 401


def test_delete_account_keeps_shared_expenses_and_promotes_admin(client, db, user_a, token_a, household_a):
    # Zweites Mitglied, das bleibt
    bob = User(id=uuid.uuid4(), email="bob2@example.com", password_hash="x", display_name="Bob")
    db.add(bob)
    db.flush()
    db.add(HouseholdMember(id=uuid.uuid4(), household_id=household_a.id, user_id=bob.id, role="member"))
    expense = Expense(
        id=uuid.uuid4(),
        household_id=household_a.id,
        paid_by_user_id=user_a.id,
        description="Einkauf",
        amount_rappen=1000,
        currency="CHF",
        split_type="even",
    )
    db.add(expense)
    db.flush()
    db.add(ExpenseShare(id=uuid.uuid4(), expense_id=expense.id, household_id=household_a.id, user_id=user_a.id, amount_rappen=500))
    db.add(ExpenseShare(id=uuid.uuid4(), expense_id=expense.id, household_id=household_a.id, user_id=bob.id, amount_rappen=500))
    db.add(RefreshToken(user_id=user_a.id, token_hash="h1", expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    db.commit()
    expense_id = expense.id
    alice_id = user_a.id

    resp = client.request("DELETE", "/api/account", json={"password": "password123"}, headers=_auth(token_a))
    assert resp.status_code == 204

    assert db.get(Household, household_a.id) is not None
    assert db.get(Expense, expense_id) is not None
    assert db.get(Expense, expense_id).paid_by_user_id == alice_id
    bob_membership = db.query(HouseholdMember).filter_by(user_id=bob.id).one()
    assert bob_membership.role == "admin"
    tokens = db.query(RefreshToken).filter_by(user_id=alice_id).all()
    assert all(t.revoked_at is not None for t in tokens)


# ---------------------------------------------------------------------------
# Rechtliches: Zustimmung bei der Registrierung, Betreiberangaben
# ---------------------------------------------------------------------------


def test_terms_required_blocks_registration(client, db, monkeypatch):
    monkeypatch.setattr(settings, "legal_terms_required", True)
    monkeypatch.setattr(settings, "legal_terms_version", "2026-10")
    payload = {"email": "t@test.com", "password": "password123", "display_name": "T", "household_name": "H"}
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == ErrorCode.TERMS_ACCEPTANCE_REQUIRED
    assert db.query(User).filter_by(email="t@test.com").first() is None

    resp = client.post("/api/auth/register", json={**payload, "accept_terms": True})
    assert resp.status_code == 200
    user = db.query(User).filter_by(email="t@test.com").one()
    assert user.terms_accepted_at is not None and user.terms_version == "2026-10"


def test_terms_optional_by_default(client, db, monkeypatch):
    monkeypatch.setattr(settings, "legal_terms_required", False)
    payload = {"email": "t2@test.com", "password": "password123", "display_name": "T", "household_name": "H"}
    assert client.post("/api/auth/register", json=payload).status_code == 200
    assert db.query(User).filter_by(email="t2@test.com").one().terms_accepted_at is None


def test_public_config_operator(client, monkeypatch):
    monkeypatch.setattr(settings, "operator_name", "Muster GmbH")
    monkeypatch.setattr(settings, "operator_address", "Musterstrasse 1 | 8000 Zürich | Schweiz")
    monkeypatch.setattr(settings, "operator_email", "hallo@example.com")
    monkeypatch.setattr(settings, "legal_terms_required", True)
    body = client.get("/api/config").json()
    assert body["operator"] == {
        "name": "Muster GmbH",
        "address_lines": ["Musterstrasse 1", "8000 Zürich", "Schweiz"],
        "email": "hallo@example.com",
    }
    assert body["terms_required"] is True
    assert body["terms_version"] == settings.legal_terms_version
