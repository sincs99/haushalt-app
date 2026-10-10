"""Minimaler Stripe-Client (REST, form-encoded) ohne SDK-Abhängigkeit.

Nur die drei Aufrufe, die der Checkout braucht (Customer, Checkout-Session,
Billing-Portal-Session) plus die Signaturprüfung für Webhooks. Netzwerkzugriff läuft
über ``_http_post``; Tests ersetzen diese Funktion.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

STRIPE_API_VERSION = "2025-08-27.basil"
WEBHOOK_TOLERANCE_SECONDS = 300


class StripeError(Exception):
    """Stripe hat einen Fehler gemeldet oder war nicht erreichbar."""


def _flatten(params: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """Verschachtelte Dicts/Listen in Stripes ``a[b][0]=x``-Form bringen."""
    out: list[tuple[str, str]] = []
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            out.extend(_flatten(value, name))
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    out.extend(_flatten(item, f"{name}[{i}]"))
                else:
                    out.append((f"{name}[{i}]", str(item)))
        elif isinstance(value, bool):
            out.append((name, "true" if value else "false"))
        elif value is not None:
            out.append((name, str(value)))
    return out


def _http_post(url: str, body: bytes, headers: dict[str, str], timeout: float = 20.0) -> dict:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — feste HTTPS-Basis
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(payload).get("error", {}).get("message", payload)
        except ValueError:
            message = payload
        raise StripeError(f"Stripe HTTP {exc.code}: {message}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise StripeError(f"Stripe unreachable: {exc}") from exc


def post(path: str, params: dict[str, Any], idempotency_key: str | None = None) -> dict:
    """POST an ``/v1/<path>``; wirft ``StripeError`` bei Fehlern."""
    secret = settings.stripe_secret_key.strip()
    if not secret:
        raise StripeError("Stripe is not configured")
    body = urllib.parse.urlencode(_flatten(params)).encode("utf-8")
    auth = base64.b64encode(f"{secret}:".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Stripe-Version": STRIPE_API_VERSION,
        "User-Agent": "haushalt-app-billing/1.0",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    url = f"{settings.stripe_api_base.rstrip('/')}/v1/{path.lstrip('/')}"
    return _http_post(url, body, headers)


# ---------------------------------------------------------------------------
# Webhook-Signatur (Stripe-Signature: t=<unix>,v1=<hex>[,v1=<hex>…])
# ---------------------------------------------------------------------------


def verify_webhook_signature(payload: bytes, header: str | None, secret: str, now: float | None = None) -> bool:
    if not header or not secret:
        return False
    timestamp: str | None = None
    signatures: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if timestamp is None or not signatures:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    current = now if now is not None else time.time()
    if abs(current - ts) > WEBHOOK_TOLERANCE_SECONDS:
        return False
    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, sig) for sig in signatures)


def sign_webhook_payload(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    """Erzeugt einen gültigen Header — für Tests und das lokale Durchspielen."""
    ts = timestamp if timestamp is not None else int(time.time())
    signed = f"{ts}.".encode() + payload
    return f"t={ts},v1={hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()}"
