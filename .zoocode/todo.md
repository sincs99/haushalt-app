# Epic 12 — Token persistence & auth lifecycle (full stack)

## Status: ✅ Abgeschlossen

---

## Zusammenfassung

### Geänderte Dateien (Backend)

| Datei | Änderung |
|---|---|
| [`backend/app/core/config.py`](backend/app/core/config.py:7) | `access_token_expire_minutes: int = 15`, `refresh_token_expire_days: int = 30` |
| [`backend/app/core/error_codes.py`](backend/app/core/error_codes.py:72) | `REFRESH_TOKEN_INVALID`, `REFRESH_TOKEN_EXPIRED`, `REFRESH_TOKEN_REUSED` |
| [`backend/app/core/security.py`](backend/app/core/security.py) | Hardcoded 7-Tage-Expiry entfernt → konfigurierbar. Neue: `create_refresh_token()`, `hash_refresh_token()`, `get_access_token_expires_in()` |
| [`backend/app/models.py`](backend/app/models.py:121) | Neues `RefreshToken`-Model (per-User, nicht per-Household) |
| [`backend/app/routers/auth.py`](backend/app/routers/auth.py) | TokenResponse erweitert, `_create_token_pair()`, Login/Register geben Token-Paare zurück, `POST /refresh` (Rotation + Reuse-Detection), `POST /logout` (idempotent) |
| [`backend/tests/conftest.py`](backend/tests/conftest.py:41) | `RefreshToken` Import ergänzt |

### Neue Dateien (Backend)

| Datei | Zweck |
|---|---|
| [`backend/migrations/versions/r1s2t3u4v5w6_add_refresh_tokens.py`](backend/migrations/versions/r1s2t3u4v5w6_add_refresh_tokens.py) | Alembic-Migration: `refresh_tokens`-Tabelle |
| [`backend/tests/test_auth_refresh.py`](backend/tests/test_auth_refresh.py) | 7 Tests: Token-Rotation, Reuse-Detection, Logout, Idempotenz |

### Geänderte Dateien (Frontend)

| Datei | Änderung |
|---|---|
| [`frontend/src/stores/auth.ts`](frontend/src/stores/auth.ts) | Komplett überarbeitet: `initialize()`, `refresh()` (single-flight), `authReady`, `isInitialized`, `_clearState()`, Logout mit redirect-Query |
| [`frontend/src/api/client.ts`](frontend/src/api/client.ts) | 401 Interceptor: refresh + retry. 403 wird durchgereicht (kein Logout). Auth-URLs ausgenommen. |
| [`frontend/src/router/index.ts`](frontend/src/router/index.ts:96) | Guard wartet auf `authReady`, redirect-Query an `/login` |
| [`frontend/src/App.vue`](frontend/src/App.vue:39) | `reconnectWithToken()` statt `connect()` für Token-Refresh-Reconnect |
| [`frontend/src/composables/useSocket.ts`](frontend/src/composables/useSocket.ts:65) | `reconnectWithToken()` Funktion hinzugefügt |
| [`frontend/src/main.ts`](frontend/src/main.ts) | Boot Order: Pinia → `authStore.initialize()` → Router |
| [`frontend/src/views/LoginView.vue`](frontend/src/views/LoginView.vue:27) | Redirect-Query nach Login auswerten |
| [`frontend/src/locales/de.json`](frontend/src/locales/de.json:52) | `sessionExpired`, `sessionExpiredMessage` |
| [`frontend/src/locales/en.json`](frontend/src/locales/en.json:52) | `sessionExpired`, `sessionExpiredMessage` |
| [`frontend/src/types/index.ts`](frontend/src/types/index.ts:273) | `TokenResponse` Interface |

### Neue Dateien (Frontend)

| Datei | Zweck |
|---|---|
| [`frontend/src/services/tokenStorage.ts`](frontend/src/services/tokenStorage.ts) | Token-Persistence-Abstraktion (localStorage, TODO: Capacitor SecureStorage) |

### Review-Dokumente

| Datei | Ergebnis |
|---|---|
| [`docs/security/epic12-auth-lifecycle-review.md`](docs/security/epic12-auth-lifecycle-review.md) | Security: PASS (0 Critical, 0 High). Business Logic: 7/7 Szenarien PASS nach Hotfixes |

### Migration
- Revision-ID: `r1s2t3u4v5w6`
- Tabelle: `refresh_tokens` (id, user_id, token_hash, expires_at, created_at, revoked_at, replaced_by_id)

### Test-Ergebnisse
- Backend: **339/339 Tests bestanden** (inkl. 7 neue)
- Frontend: `vue-tsc --noEmit` ✅, `npm run check:locales` ✅ (617 Keys)

---

## Acceptance Criteria Bewertung

| # | Kriterium | Status |
|---|---|---|
| 1 | F5-Reload → User bleibt eingeloggt | ✅ |
| 2 | Browser schließen + öffnen → noch eingeloggt | ✅ |
| 3 | Access-Token expired → transparenter Refresh | ✅ |
| 4 | Refresh-Token expired → Login mit Redirect zurück | ✅ |
| 5 | Logout Tab A → Tab B 401 → Login | ⚠️ WARN (kein Cross-Tab-Sync, funktioniert über Access-Token-TTL) |
| 6 | Foreign Household → 403, kein Logout | ✅ |
| 7 | Socket Reconnect nach Refresh | ✅ |
| 8 | Alle Tests grün, locales grün, vue-tsc grün | ✅ |

### Offene Punkte (nicht-blockierend, für Follow-up Epics)
- **Rate-Limiting** auf `/api/auth/login` und `/api/auth/refresh` (Security Finding F-04)
- **Token-Cleanup-Job** für abgelaufene/revoked Refresh-Tokens (Security Finding F-05)
- **Cross-Tab-Logout** via `window.addEventListener('storage', ...)` (Business Logic WARN)
- **Capacitor SecureStorage** statt localStorage für native Builds (geplant)
