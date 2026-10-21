# Native Apps für iOS und Android (Capacitor)

**Stand:** 2026-10-09 — Vorbereitung abgeschlossen, native Projekte noch nicht erzeugt.

Die Web-App (Vue 3, PWA) wird unverändert in eine native Hülle verpackt
([Capacitor](https://capacitorjs.com)). Es gibt **einen** Frontend-Code für Web, iOS und
Android; Unterschiede entscheidet `frontend/src/services/platform.ts` zur Laufzeit
(`isNativeApp()`). Dieses Dokument beschreibt, was dafür bereits im Code steckt und welche
Schritte für die Store-Veröffentlichung folgen.

## 1. Was bereits vorbereitet ist

| Thema | Web (PWA) | Native App | Stand im Code |
|---|---|---|---|
| Anmeldung / Refresh-Token | HttpOnly-Cookie `casa_rt` + CSRF-Header | Token im Body, Ablage über `nativeRefreshToken` (SecureStorage → Preferences → localStorage) | `api/client.ts` (`authRequestConfig`), `services/tokenStorage.ts`, `stores/auth.ts`; Backend unterstützt beide Pfade (`routers/auth.py`) |
| API-Adresse | same-origin | absolut über `VITE_API_URL` beim Build | `api/client.ts` |
| Abos / Premium | Stripe-Checkout | Store-Abrechnung (Pflicht bei Apple/Google); Stripe-Button ausgeblendet | `components/BillingCard.vue`, `docs/monetization.md` |
| Konto löschen (Apple-Pflicht 5.1.1(v)) | ✅ | ✅ | `DELETE /api/account`, `AccountSettingsCard.vue` |
| Datenschutz / AGB / Impressum (Store-Pflicht) | `/legal/privacy`, `/legal/terms`, `/legal/imprint` | gleiche Seiten | `views/LegalView.vue`, `public/legal/*.md` |
| E-Mail-Bestätigung, Passwort vergessen | ✅ | ✅ (Links öffnen die Web-Adresse; Deep-Links siehe unten) | `routers/account.py` |
| Push | Web Push (VAPID) | **offen**: APNs/FCM | siehe Abschnitt 4 |
| Offline | Service Worker + IndexedDB | WebView-Cache; Service Worker auf iOS-WKWebView eingeschränkt | `docs/offline-first-phase2.md` |

Konfiguration: `frontend/capacitor.config.json` (App-ID `ch.example.haushalt` ersetzen).

## 2. Native Projekte erzeugen

```bash
cd frontend
npm install @capacitor/core @capacitor/cli @capacitor/ios @capacitor/android @capacitor/preferences
# Build mit absoluter API-Adresse (die App läuft nicht same-origin)
VITE_API_URL=https://casa.example.com npm run build
npx cap add ios
npx cap add android
npx cap sync
npx cap open ios      # Xcode (macOS nötig)
npx cap open android  # Android Studio
```

Empfohlen für den Refresh-Token: `capacitor-secure-storage-plugin` (Keychain/Keystore).
Sobald das Plugin registriert ist, nutzt `nativeRefreshToken` es automatisch; ohne Plugin
fällt es auf `@capacitor/preferences` zurück (App-privat, nicht verschlüsselt).

**Backend:** die nativen Origins in `CORS_ORIGINS` aufnehmen, z. B.
`https://casa.example.com,capacitor://localhost,https://localhost`
(iOS: `capacitor://localhost`; Android mit `androidScheme: https`: `https://localhost`).

## 3. Deep-Links (E-Mail-Links in der App öffnen)

Die Links in System-Mails (`/verify-email?token=…`, `/reset-password?token=…`) zeigen auf
`APP_BASE_URL`. Damit sie in der App statt im Browser aufgehen:

- iOS: Universal Links (`apple-app-site-association` unter `/.well-known/`, Associated Domains)
- Android: App Links (`assetlinks.json` unter `/.well-known/`, `autoVerify` im Manifest)
- `@capacitor/app`: `appUrlOpen` abonnieren und per `router.push(url.pathname + url.search)` in die
  Route springen

Ohne Deep-Links funktionieren die Links trotzdem — im Browser; die Bestätigung gilt für das Konto.

## 4. Push-Benachrichtigungen

Web Push (`push-sw.js`, VAPID) läuft nicht in der nativen WebView. Plan:

1. `@capacitor/push-notifications` einbinden; Token vom Gerät holen (APNs/FCM)
2. Backend: `push_subscriptions` um `platform` (`web` | `ios` | `android`) und Geräte-Token
   erweitern, Versand in `services/push_service.py` je Plattform (Web Push bzw. FCM HTTP v1, der
   auch APNs bedient)
3. Erinnerungs-Logik bleibt unverändert (gleiche Payloads)

## 5. Store-Abos (Premium in der App kaufen)

Apple und Google verlangen für digitale Abos die eigene Abrechnung. Das Datenmodell ist dafür
vorbereitet (`subscriptions.provider = apple | google`, `services/billing/service.py`):

1. Produkte anlegen: App Store Connect (Auto-Renewable Subscription) und Google Play Console
   (Subscription), Produkt-IDs z. B. `premium_monthly`, `premium_yearly`
2. In der App kaufen — am einfachsten über RevenueCat (`@revenuecat/purchases-capacitor`) oder
   direkt StoreKit 2 / Play Billing; die Haushalt-ID als `appAccountToken` / `obfuscatedAccountId`
   mitgeben, damit der Server das Abo dem Haushalt zuordnen kann
3. Server-Benachrichtigungen empfangen: App Store Server Notifications V2 (signierte JWS) und
   Google Real-time Developer Notifications (Pub/Sub). Jeder Handler verifiziert die Nachricht und
   ruft `apply_subscription(db, household, SubscriptionState(provider="apple"|"google", …))` auf —
   genau wie der Stripe-Webhook (`routers/billing.py`)
4. Kündigen/Verwalten passiert in den Store-Einstellungen; die Tarif-Karte zeigt dann nur den Status

Preise in den Stores sind unabhängig von Stripe; die Store-Provision (15–30 %) einpreisen.

## 6. Checkliste vor der Veröffentlichung

- [ ] App-ID, Name, Icons, Splash (`@capacitor/assets`)
- [ ] `CORS_ORIGINS` mit nativen Origins, `VITE_API_URL` im Build
- [ ] Konto löschen in der App auffindbar (Einstellungen → Konto) ✅
- [ ] Datenschutzerklärung und AGB als öffentliche URLs (`/legal/privacy`, `/legal/terms`) ✅
- [ ] Apple: Privacy Manifest (`PrivacyInfo.xcprivacy`), «App Privacy»-Angaben, Sign in nur per
      E-Mail/Passwort → kein «Sign in with Apple»-Zwang (gilt nur bei Drittanbieter-Logins)
- [ ] Google: Data-Safety-Formular, Ziel-API-Level aktuell
- [ ] Abos: Produkte, Server-Notifications, Testkäufe in Sandbox/Lizenztester
- [ ] Push: APNs-Key, Firebase-Projekt
- [ ] Test auf echten Geräten (iPhone + Android), insbesondere Kamera-Upload (HEIC), NFC-Tags
      (Web NFC gibt es nur in Chrome/Android; iOS braucht ein Core-NFC-Plugin), Offline-Verhalten
