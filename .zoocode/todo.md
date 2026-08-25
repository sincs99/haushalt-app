# Epic 12b — Auth Hardening (follow-up to Epic 12)

## Status: 🟢 Backend Done /  Frontend In Progress

---

## Part A — Bugs

### A1. Transport errors must never clear tokens (Frontend)
- `initialize()`: non-401 errors → keep tokens, stay "logged in"
- `client.ts` interceptor: only `logout()` on auth rejection (401), not on network/5xx
- Router guard: `/no-household` redirect nur wenn `user !== null`

### A2. Multi-tab refresh conflict (Frontend + Backend)
- Frontend: `_doRefresh()` liest tokens aus `tokenStorage.get()` statt `refreshToken.value`
- Frontend: `storage` event listener für Cross-Tab-Sync
- ✅ Backend: `refresh_token_reuse_grace_seconds: int = 30` in config
- ✅ Backend: Grace-Window-Logik im refresh_endpoint
- ✅ Backend: `_create_token_pair` refactored → returns `(TokenResponse, RefreshToken)`

### A3. Concurrent logout guard (Frontend)
- `logout()` single-flight
- `logout({ reason?: 'user' | 'expired' })`: nur `expired` setzt `?redirect=`

## Part B — Native-readiness

### B1. Async TokenStorage (Frontend)
- Interface `get(): Promise<Tokens | null>`, `set(): Promise<void>`, `clear(): Promise<void>`
- Alle Call-Sites anpassen (initialize, login, register, _doRefresh, _clearState)

## Part C — Hardening

### C1. Rate limiting (Backend) ✅
- ✅ `slowapi==0.1.9` installiert + `backend/app/core/rate_limit.py` erstellt
- ✅ Login: 5/min per IP, Register: 3/hour per IP
- ✅ Error code: `RATE_LIMITED` → Frontend bekommt `429` mit `{"detail": {"code": "RATE_LIMITED", "message": "Too many requests"}}`
- ✅ Test: 6. Login → 429

### C2. Lazy refresh-token cleanup (Backend) ✅
- ✅ In `refresh_endpoint`: nach Rotation alte expired/revoked Tokens löschen

### C3. JWT secret startup check (Backend) ✅
- ✅ In `main.py`: Prüfe jwt_secret_key gegen .env.example Placeholder und min. 32 Zeichen

---

## Dateien-Übersicht

### Backend (zu ändern)
| Datei | Tasks |
|---|---|
| `backend/app/core/config.py` | A2 (grace seconds), C1 (rate limit config wenn nötig) |
| `backend/app/core/error_codes.py` | C1 (RATE_LIMITED) |
| `backend/app/routers/auth.py` | A2 (grace window + _create_token_pair refactor), C1 (rate limits), C2 (cleanup) |
| `backend/app/main.py` | C1 (slowapi middleware), C3 (JWT check) |
| `backend/requirements.txt` | C1 (slowapi) |
| `backend/tests/test_auth_refresh.py` | A2 (grace window tests), C1 (rate limit test), C3 (JWT check test) |
| `backend/tests/conftest.py` | C1 (raise limits für Tests) |

### Frontend (zu ändern)
| Datei | Tasks |
|---|---|
| `frontend/src/services/tokenStorage.ts` | B1 (async interface) |
| `frontend/src/stores/auth.ts` | A1, A2, A3, B1 |
| `frontend/src/api/client.ts` | A1 (isAuthRejection) |
| `frontend/src/router/index.ts` | A1 (guard: user !== null check) |

---

## ⚠️ Frontend-Hinweise (nach Backend-Änderungen)

- **Neuer HTTP-Status 429**: Login/Register können jetzt `429 Too Many Requests` zurückgeben. Error-Code: `RATE_LIMITED`. Frontend sollte `errors.RATE_LIMITED` in i18n-Dateien ergänzen.
- **Grace Window (30s)**: Wenn zwei Tabs gleichzeitig einen Refresh machen, wird der zweite Tab jetzt NICHT mehr sofort mit 401 abgewiesen — das Backend gibt stattdessen ein neues Token-Paar zurück. Das Frontend muss keinen Retry bauen, aber es profitiert davon.
- **Refresh-Endpoint API ist unverändert**: Request/Response-Schema für `/api/auth/refresh`, `/api/auth/login`, `/api/auth/register` und `/api/auth/logout` sind gleich geblieben.

---

## Acceptance Criteria
1. [ ] Backend offline → tokens bleiben, Backend wieder da → eingeloggt
2. [x] Zwei Tabs, ACCESS_TOKEN_EXPIRE_MINUTES=1 → beide bleiben eingeloggt (Backend-seitig via Grace Window)
3. [ ] Logout Tab A → Tab B → /login innerhalb 1 Sekunde
4. [x] Gleicher Refresh-Token 2x in 5s → OK; nach 60s nochmal → 401
5. [x] 6. Login-Versuch in 1 Min → 429
6. [x] JWT Placeholder → Startup-Fehler
7. [ ] Manueller Logout → /login ohne redirect; Expiry → mit redirect
8. [x] Alle Backend-Tests grün (345 passed), [ ] vue-tsc + check:locales
