"""Tests: Tarife (entitlements), Stripe-Billing (Checkout, Webhook) und Plattform-Admin."""
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.models import BillingEvent, HouseholdMember, RefreshToken, Subscription, User
from app.services import entitlements
from app.services.billing import stripe_client
from app.services.billing.service import SubscriptionState, apply_subscription

WEBHOOK_SECRET = "whsec_test_secret"


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def billing(monkeypatch):
    """SaaS-Modus: Tarife aktiv, Stripe konfiguriert, kleine Gratis-Limits."""
    monkeypatch.setattr(settings, "billing_enabled", True)
    monkeypatch.setattr(settings, "plan_free_max_members", 2)
    monkeypatch.setattr(settings, "plan_free_storage_mb", 1)
    monkeypatch.setattr(settings, "plan_free_ai_daily_limit", 0)
    monkeypatch.setattr(settings, "plan_premium_ai_daily_limit", 50)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "stripe_price_id_monthly", "price_month")
    monkeypatch.setattr(settings, "stripe_price_id_yearly", "")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")


@pytest.fixture()
def verified(db, user_a):
    user_a.email_verified_at = datetime.now(timezone.utc)
    db.commit()
    return user_a


def _add_member(db, household, email="m@example.com"):
    u = User(id=uuid.uuid4(), email=email, password_hash="x", display_name="M")
    db.add(u)
    db.flush()
    db.add(HouseholdMember(id=uuid.uuid4(), household_id=household.id, user_id=u.id, role="member"))
    db.commit()
    return u


# ---------------------------------------------------------------------------
# Entitlements
# ---------------------------------------------------------------------------


def test_selfhosted_uses_global_limits(db, household_a, monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", False)
    monkeypatch.setattr(settings, "household_storage_quota_mb", 7)
    monkeypatch.setattr(settings, "ai_daily_limit_per_household", 11)
    limits = entitlements.limits_for_household(household_a)
    assert limits.key == "selfhosted"
    assert limits.max_members is None
    assert limits.storage_bytes == 7 * 1024 * 1024
    assert limits.ai_daily_limit == 11
    assert entitlements.can_add_member(db, household_a)


def test_free_plan_limits_and_expiry(db, household_a, billing):
    assert entitlements.effective_plan(household_a) == "free"
    limits = entitlements.limits_for_household(household_a)
    assert limits.max_members == 2 and not limits.ai_included

    household_a.plan = "premium"
    household_a.plan_expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    assert entitlements.effective_plan(household_a) == "premium"
    household_a.plan_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert entitlements.effective_plan(household_a) == "free"
    household_a.plan_expires_at = None
    assert entitlements.effective_plan(household_a) == "premium"


def test_member_limit_blocks_join_and_register(client, db, household_a, user_a, user_b, token_b, billing):
    _add_member(db, household_a)  # 2 Mitglieder = Limit des Gratis-Tarifs
    resp = client.post("/api/households/join", json={"invite_code": household_a.invite_code}, headers=_auth(token_b))
    assert resp.status_code == 402
    assert resp.json()["detail"]["code"] == ErrorCode.PLAN_MEMBER_LIMIT_REACHED

    resp = client.post("/api/auth/register", json={
        "email": "third@test.com", "password": "password123", "display_name": "T",
        "invite_code": household_a.invite_code,
    })
    assert resp.status_code == 402
    assert db.query(User).filter_by(email="third@test.com").first() is None

    household_a.plan = "premium"
    db.commit()
    resp = client.post("/api/households/join", json={"invite_code": household_a.invite_code}, headers=_auth(token_b))
    assert resp.status_code == 200


def test_storage_quota_follows_plan(client, db, household_a, token_a, billing):
    resp = client.get(f"/api/households/{household_a.id}/documents/storage", headers=_auth(token_a))
    assert resp.status_code == 200
    assert resp.json()["quota_bytes"] == 1 * 1024 * 1024
    household_a.plan = "premium"
    db.commit()
    resp = client.get(f"/api/households/{household_a.id}/documents/storage", headers=_auth(token_a))
    assert resp.json()["quota_bytes"] == settings.plan_premium_storage_mb * 1024 * 1024


def test_ai_requires_premium(client, db, household_a, token_a, billing):
    household_a.ai_enabled = True
    db.commit()
    resp = client.post(
        f"/api/households/{household_a.id}/ai/recipe",
        json={"ingredients": ["Tomaten", "Reis"]},
        headers=_auth(token_a),
    )
    assert resp.status_code == 402
    assert resp.json()["detail"]["code"] == ErrorCode.PLAN_UPGRADE_REQUIRED
    resp = client.get(f"/api/households/{household_a.id}/ai/settings", headers=_auth(token_a))
    assert resp.json()["daily_limit"] == 0
    household_a.plan = "premium"
    db.commit()
    resp = client.get(f"/api/households/{household_a.id}/ai/settings", headers=_auth(token_a))
    assert resp.json()["daily_limit"] == 50


def test_me_reports_plan(client, db, household_a, token_a, billing):
    me = client.get("/api/auth/me", headers=_auth(token_a)).json()
    assert me["households"][0]["plan"] == "free"
    assert me["is_platform_admin"] is False


# ---------------------------------------------------------------------------
# Abo → Tarif
# ---------------------------------------------------------------------------


def test_apply_subscription_sets_and_clears_plan(db, household_a, billing):
    end = datetime.now(timezone.utc) + timedelta(days=30)
    apply_subscription(db, household_a, SubscriptionState("stripe", "sub_1", "active", end))
    db.refresh(household_a)
    assert household_a.plan == "premium"
    assert household_a.plan_expires_at.replace(tzinfo=timezone.utc) == end + timedelta(days=settings.plan_grace_days)

    apply_subscription(db, household_a, SubscriptionState("stripe", "sub_1", "canceled", end))
    db.refresh(household_a)
    assert household_a.plan == "free"
    assert household_a.plan_expires_at is None
    assert db.query(Subscription).count() == 1


def test_other_active_subscription_keeps_premium(db, household_a, billing):
    apply_subscription(db, household_a, SubscriptionState("apple", "orig_1", "active", None))
    apply_subscription(db, household_a, SubscriptionState("stripe", "sub_1", "active", None))
    apply_subscription(db, household_a, SubscriptionState("stripe", "sub_1", "canceled", None))
    db.refresh(household_a)
    assert household_a.plan == "premium"


# ---------------------------------------------------------------------------
# Billing-Endpunkte
# ---------------------------------------------------------------------------


def test_billing_status(client, db, household_a, token_a, billing):
    resp = client.get(f"/api/households/{household_a.id}/billing", headers=_auth(token_a))
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"] == "free"
    assert body["limits"]["max_members"] == 2
    assert body["usage"]["members"] == 1
    assert body["checkout_available"] is True
    assert body["portal_available"] is False
    assert body["intervals"] == ["month"]
    assert body["subscription"] is None


def test_billing_status_selfhosted(client, db, household_a, token_a, monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", False)
    body = client.get(f"/api/households/{household_a.id}/billing", headers=_auth(token_a)).json()
    assert body["billing_enabled"] is False
    assert body["plan"] == "selfhosted"
    assert body["checkout_available"] is False


def test_checkout_requires_verified_email(client, db, household_a, token_a, billing):
    resp = client.post(f"/api/households/{household_a.id}/billing/checkout", json={"interval": "month"}, headers=_auth(token_a))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == ErrorCode.EMAIL_VERIFICATION_REQUIRED


def test_checkout_creates_customer_and_session(client, db, household_a, token_a, verified, billing):
    calls = []

    def fake_post(url, body, headers, timeout=20.0):
        calls.append((url, body.decode(), headers))
        if url.endswith("/v1/customers"):
            return {"id": "cus_123"}
        if url.endswith("/v1/checkout/sessions"):
            return {"id": "cs_1", "url": "https://checkout.stripe.com/c/pay/cs_1"}
        raise AssertionError(url)

    with patch("app.services.billing.stripe_client._http_post", side_effect=fake_post):
        resp = client.post(
            f"/api/households/{household_a.id}/billing/checkout",
            json={"interval": "month"},
            headers=_auth(token_a),
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["url"].startswith("https://checkout.stripe.com/")
    db.refresh(household_a)
    assert household_a.stripe_customer_id == "cus_123"
    customer_call, session_call = calls
    assert "Idempotency-Key" in customer_call[2]
    assert "mode=subscription" in session_call[1]
    assert "line_items%5B0%5D%5Bprice%5D=price_month" in session_call[1]
    assert f"client_reference_id={household_a.id}" in session_call[1]
    assert customer_call[2]["Authorization"].startswith("Basic ")

    # Jahres-Preis nicht konfiguriert
    with patch("app.services.billing.stripe_client._http_post", side_effect=fake_post):
        resp = client.post(
            f"/api/households/{household_a.id}/billing/checkout",
            json={"interval": "year"},
            headers=_auth(token_a),
        )
    assert resp.status_code == 422


def test_checkout_admin_only_and_provider_error(client, db, household_a, token_a, verified, billing):
    bob = _add_member(db, household_a)
    from app.core.security import create_access_token

    resp = client.post(
        f"/api/households/{household_a.id}/billing/checkout",
        json={},
        headers=_auth(create_access_token(str(bob.id))),
    )
    assert resp.status_code == 403

    with patch("app.services.billing.stripe_client._http_post", side_effect=stripe_client.StripeError("down")):
        resp = client.post(f"/api/households/{household_a.id}/billing/checkout", json={}, headers=_auth(token_a))
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == ErrorCode.BILLING_PROVIDER_ERROR


def test_checkout_disabled_without_billing(client, db, household_a, token_a, verified, monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", False)
    resp = client.post(f"/api/households/{household_a.id}/billing/checkout", json={}, headers=_auth(token_a))
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == ErrorCode.BILLING_DISABLED


def test_portal_requires_customer(client, db, household_a, token_a, billing):
    resp = client.post(f"/api/households/{household_a.id}/billing/portal", headers=_auth(token_a))
    assert resp.status_code == 404
    household_a.stripe_customer_id = "cus_9"
    db.commit()
    with patch("app.services.billing.stripe_client._http_post", return_value={"url": "https://billing.stripe.com/p/x"}):
        resp = client.post(f"/api/households/{household_a.id}/billing/portal", headers=_auth(token_a))
    assert resp.status_code == 200
    assert resp.json()["url"].startswith("https://billing.stripe.com/")


# ---------------------------------------------------------------------------
# Stripe-Webhook
# ---------------------------------------------------------------------------


def _event(event_id, event_type, obj):
    return json.dumps({"id": event_id, "type": event_type, "data": {"object": obj}}).encode()


def _post_event(client, payload, secret=WEBHOOK_SECRET, header=None):
    sig = header if header is not None else stripe_client.sign_webhook_payload(payload, secret)
    return client.post(
        "/api/billing/webhooks/stripe",
        content=payload,
        headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
    )


def test_webhook_rejects_bad_signature(client, db, billing):
    payload = _event("evt_1", "customer.subscription.updated", {})
    resp = _post_event(client, payload, secret="wrong")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == ErrorCode.WEBHOOK_SIGNATURE_INVALID
    assert _post_event(client, payload, header="garbage").status_code == 400
    # Zu alter Zeitstempel
    old = stripe_client.sign_webhook_payload(payload, WEBHOOK_SECRET, timestamp=1_000_000)
    assert _post_event(client, payload, header=old).status_code == 400


def test_webhook_subscription_lifecycle(client, db, household_a, billing):
    period_end = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
    sub = {
        "id": "sub_42",
        "status": "active",
        "customer": "cus_42",
        "cancel_at_period_end": False,
        "metadata": {"household_id": str(household_a.id)},
        "items": {"data": [{"current_period_end": period_end}]},
    }
    resp = _post_event(client, _event("evt_1", "customer.subscription.created", sub))
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"] == "subscription_applied"
    db.refresh(household_a)
    assert household_a.plan == "premium"
    row = db.query(Subscription).filter_by(provider="stripe", provider_subscription_id="sub_42").one()
    assert row.status == "active"
    assert int(row.current_period_end.replace(tzinfo=timezone.utc).timestamp()) == period_end

    # Gleiches Event erneut → Duplikat, keine zweite Verarbeitung
    resp = _post_event(client, _event("evt_1", "customer.subscription.created", sub))
    assert resp.json()["result"] == "duplicate"
    assert db.query(BillingEvent).count() == 1

    # Kündigung zum Periodenende → bleibt Premium, Flag gesetzt
    sub2 = {**sub, "cancel_at_period_end": True}
    _post_event(client, _event("evt_2", "customer.subscription.updated", sub2))
    db.refresh(row)
    assert row.cancel_at_period_end is True
    db.refresh(household_a)
    assert household_a.plan == "premium"

    # Abo gelöscht → Gratis
    sub3 = {**sub, "status": "canceled"}
    _post_event(client, _event("evt_3", "customer.subscription.deleted", sub3))
    db.refresh(household_a)
    assert household_a.plan == "free"


def test_webhook_checkout_links_customer_and_falls_back_to_customer_lookup(client, db, household_a, billing):
    session = {"id": "cs_1", "customer": "cus_77", "client_reference_id": str(household_a.id)}
    resp = _post_event(client, _event("evt_c1", "checkout.session.completed", session))
    assert resp.json()["result"] == "customer_linked"
    db.refresh(household_a)
    assert household_a.stripe_customer_id == "cus_77"

    # Abo-Event ohne metadata → Zuordnung über die Kunden-ID
    sub = {"id": "sub_77", "status": "trialing", "customer": "cus_77", "current_period_end": 4_000_000_000}
    resp = _post_event(client, _event("evt_s1", "customer.subscription.created", sub))
    assert resp.json()["result"] == "subscription_applied"
    db.refresh(household_a)
    assert household_a.plan == "premium"

    # Unbekannter Kunde → ignoriert
    sub = {"id": "sub_x", "status": "active", "customer": "cus_unknown"}
    resp = _post_event(client, _event("evt_s2", "customer.subscription.created", sub))
    assert resp.json()["result"] == "ignored_no_household"


def test_webhook_disabled_without_billing(client, db, monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", False)
    resp = client.post("/api/billing/webhooks/stripe", content=b"{}", headers={"Stripe-Signature": "t=1,v1=x"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Plattform-Admin
# ---------------------------------------------------------------------------


@pytest.fixture()
def platform_admin(db, user_a):
    user_a.is_platform_admin = True
    db.commit()
    return user_a


def test_admin_endpoints_require_platform_admin(client, db, user_a, token_a):
    for method, path in [
        ("GET", "/api/admin/overview"),
        ("GET", "/api/admin/households"),
        ("GET", "/api/admin/users"),
    ]:
        resp = client.request(method, path, headers=_auth(token_a))
        assert resp.status_code == 403, path
        assert resp.json()["detail"]["code"] == ErrorCode.PLATFORM_ADMIN_REQUIRED


def test_admin_overview_and_lists(client, db, platform_admin, token_a, household_a, household_b, user_b, billing):
    body = client.get("/api/admin/overview", headers=_auth(token_a)).json()
    assert body["users_total"] == 2
    assert body["households_total"] == 2
    assert body["households_by_plan"] == {"free": 2}

    households = client.get("/api/admin/households", params={"q": "alpha"}, headers=_auth(token_a)).json()
    assert [h["name"] for h in households] == ["Haushalt Alpha"]
    assert households[0]["member_count"] == 1
    assert households[0]["effective_plan"] == "free"

    by_id = client.get("/api/admin/households", params={"q": str(household_b.id)}, headers=_auth(token_a)).json()
    assert [h["id"] for h in by_id] == [str(household_b.id)]

    users = client.get("/api/admin/users", params={"q": "bob"}, headers=_auth(token_a)).json()
    assert [u["email"] for u in users] == ["bob@example.com"]
    assert users[0]["household_count"] == 1


def test_admin_sets_plan_manually(client, db, platform_admin, token_a, household_b, billing):
    expires = (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()
    resp = client.patch(
        f"/api/admin/households/{household_b.id}/plan",
        json={"plan": "premium", "expires_at": expires, "note": "Beta-Tester"},
        headers=_auth(token_a),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["effective_plan"] == "premium"
    sub = db.query(Subscription).filter_by(household_id=household_b.id).one()
    assert sub.provider == "manual" and sub.note == "Beta-Tester"

    resp = client.patch(f"/api/admin/households/{household_b.id}/plan", json={"plan": "free"}, headers=_auth(token_a))
    assert resp.json()["effective_plan"] == "free"

    resp = client.patch(f"/api/admin/households/{household_b.id}/plan", json={"plan": "gold"}, headers=_auth(token_a))
    assert resp.status_code == 422
    resp = client.patch(f"/api/admin/households/{uuid.uuid4()}/plan", json={"plan": "free"}, headers=_auth(token_a))
    assert resp.status_code == 404


def test_admin_deactivates_user(client, db, platform_admin, token_a, user_b, token_b):
    db.add(RefreshToken(user_id=user_b.id, token_hash="rt-b", expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
    db.commit()

    # Sich selbst sperren → 422
    resp = client.patch(f"/api/admin/users/{platform_admin.id}", json={"is_active": False}, headers=_auth(token_a))
    assert resp.status_code == 422

    resp = client.patch(f"/api/admin/users/{user_b.id}", json={"is_active": False}, headers=_auth(token_a))
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
    # Gesperrt: Token-Nutzung 401 (ACCOUNT_DISABLED), Login 403, Refresh widerrufen
    resp = client.get("/api/auth/me", headers=_auth(token_b))
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == ErrorCode.ACCOUNT_DISABLED
    resp = client.post("/api/auth/login", data={"username": "bob@example.com", "password": "password456"})
    assert resp.status_code == 403
    assert db.query(RefreshToken).filter_by(user_id=user_b.id).one().revoked_at is not None

    # Entsperren
    resp = client.patch(f"/api/admin/users/{user_b.id}", json={"is_active": True}, headers=_auth(token_a))
    assert resp.json()["is_active"] is True
    assert client.get("/api/auth/me", headers=_auth(token_b)).status_code == 200


def test_refresh_rejected_for_disabled_user(client, db, user_b):
    login = client.post("/api/auth/login", data={"username": "bob@example.com", "password": "password456"})
    refresh = login.json()["refresh_token"]
    user_b.is_active = False
    db.commit()
    resp = client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == ErrorCode.ACCOUNT_DISABLED


def test_public_config_billing_flags(client, billing):
    body = client.get("/api/config").json()
    assert body["billing_enabled"] is True and body["checkout_available"] is True


def test_stripe_flatten_params():
    pairs = stripe_client._flatten({"a": {"b": [1, {"c": True}]}, "d": None, "e": "x"})
    assert pairs == [("a[b][0]", "1"), ("a[b][1][c]", "true"), ("e", "x")]
