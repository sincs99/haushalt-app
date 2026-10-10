# Monetarisierung: Tarife, Stripe, Betreiber-Zugang

**Stand:** 2026-10-09

## 1. Modell

- **Self-Hosting** (`BILLING_ENABLED=false`, Standard): keine Tarife. Jeder Haushalt hat alle
  Funktionen mit den globalen Limits `HOUSEHOLD_STORAGE_QUOTA_MB` und
  `AI_DAILY_LIMIT_PER_HOUSEHOLD`. Die Tarif-Karte ist ausgeblendet.
- **SaaS-Betrieb** (`BILLING_ENABLED=true`): jeder Haushalt hat einen Tarif.

| Tarif | Mitglieder | Speicher | KI-Assistent | Herkunft |
|---|---|---|---|---|
| `free` | `PLAN_FREE_MAX_MEMBERS` (3) | `PLAN_FREE_STORAGE_MB` (200) | `PLAN_FREE_AI_DAILY_LIMIT` (0 = nicht enthalten) | Standard |
| `premium` | `PLAN_PREMIUM_MAX_MEMBERS` (0 = unbegrenzt) | `PLAN_PREMIUM_STORAGE_MB` (5120) | `PLAN_PREMIUM_AI_DAILY_LIMIT` (50) | Stripe, App Store, Google Play oder manuell |

Prüfpunkte im Backend (`services/entitlements.py`):

- Beitritt und Registrierung mit Einladungscode → `402 PLAN_MEMBER_LIMIT_REACHED`
- Upload (Dokumente, Fotos) → `422 STORAGE_QUOTA_EXCEEDED` mit dem Limit des Tarifs
- KI-Assistent → `402 PLAN_UPGRADE_REQUIRED`, Tageslimit des Tarifs
- Bestehende Daten über dem Limit bleiben erhalten; nur Neues wird abgelehnt.

Ablauf eines bezahlten Tarifs: `households.plan_expires_at` = Periodenende + `PLAN_GRACE_DAYS`.
Danach gilt `free`, bis ein Webhook/Admin den Tarif erneuert.

## 2. Stripe einrichten

1. Produkt «Premium» mit zwei Preisen (monatlich, jährlich, wiederkehrend) anlegen.
2. Webhook-Endpoint `https://<app>/api/billing/webhooks/stripe` mit den Events
   `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`.
3. Kundenportal aktivieren (Stripe → Settings → Billing → Customer portal): Kündigen,
   Zahlungsmittel, Rechnungen.
4. `.env.prod`:

```
BILLING_ENABLED=true
STRIPE_SECRET_KEY=sk_live_…
STRIPE_WEBHOOK_SECRET=whsec_…
STRIPE_PRICE_ID_MONTHLY=price_…
STRIPE_PRICE_ID_YEARLY=price_…
APP_BASE_URL=https://casa.example.com
LEGAL_TERMS_REQUIRED=true
```

Ablauf: Haushalts-Admin mit bestätigter E-Mail → «Auf Premium wechseln» → Stripe Checkout
(Customer wird mit `household_id` in den Metadaten angelegt) → Rückkehr auf
`/household?billing=success` → Webhook `customer.subscription.created` setzt `premium`.
Der Webhook ist idempotent (`billing_events`); Signaturprüfung mit 5 Minuten Toleranz.

Lokal testen:

```bash
stripe listen --forward-to localhost:8000/api/billing/webhooks/stripe
stripe trigger customer.subscription.created
```

Steuern: Stripe Tax aktivieren oder einen Merchant of Record (z. B. Paddle, Lemon Squeezy)
vorschalten; dessen Webhook landet ebenfalls in `apply_subscription`.

## 3. App-Store-Abos

Native Apps müssen die Store-Abrechnung nutzen; der Stripe-Button ist dort ausgeblendet. Die
Anbindung (Apple App Store Server Notifications, Google RTDN) ist in
[`mobile-apps.md`](mobile-apps.md), Abschnitt 5, beschrieben und mündet in dasselbe
`apply_subscription`.

## 4. Betreiber-Zugang

```bash
docker compose exec backend python -m scripts.make_platform_admin --email admin@example.com
```

Danach erscheint in den Einstellungen «Betreiber-Ansicht öffnen» (`/admin`):

- Kennzahlen (Konten, Haushalte, Tarife, aktive Abos)
- Haushalte suchen, Tarif manuell setzen (mit Ablaufdatum; z. B. Beta-Tester, Kulanz)
- Konten sperren/entsperren (Sperre beendet alle Sitzungen)

Die API (`/api/admin/*`) liefert keine Haushaltsinhalte.

## 5. Betrieb und Pflichten

- E-Mail-Versand (SMTP) ist Voraussetzung: Checkout verlangt eine bestätigte Adresse.
- Rechtstexte unter `frontend/public/legal/` anpassen und prüfen lassen; Betreiberangaben in
  `OPERATOR_*` eintragen; `LEGAL_TERMS_REQUIRED=true` setzen.
- Widerruf: 14 Tage bei Web-Käufen (in den AGB-Vorlagen enthalten); Rückerstattungen über
  das Stripe-Dashboard, der Webhook setzt den Tarif anschliessend zurück.
- Kennzahlen für den Start: Registrierungen, aktive Haushalte, Konversion free → premium,
  Kündigungen (`subscriptions.status`), KI-Kosten (`ai_usage`).

## 6. Offene Punkte

- App-Store-/Play-Abos (Handler für Server-Notifications)
- Rechnungs-E-Mails verschickt Stripe; bei einem Merchant of Record dessen Mails prüfen
- Export der eigenen Daten (DSGVO Art. 20) als ZIP — Konto löschen existiert, Export noch nicht
