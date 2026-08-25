# Epic 14 — Production Deployment (Docker + NPM)

## Status: ✅ COMPLETE

## Geänderte / Neue Dateien

### Neue Dateien
| Datei | Part | Beschreibung |
|-------|------|--------------|
| `docker-compose.prod.yml` | A1 | Standalone Production Compose (keine Ports, Healthchecks, NPM-Netzwerk) |
| `.env.prod.example` | A2 | Production-Env-Vorlage mit allen Variablen + Kommentaren |
| `backend/tests/test_rate_limit_proxy.py` | C1 | 2 Tests: separate IP-Buckets + strukturierte 429-Response |
| `docs/deployment.md` | F | Vollständige Deployment-Doku (7 Abschnitte) |

### Geänderte Dateien
| Datei | Part | Änderungen |
|-------|------|------------|
| `backend/Dockerfile` | B1 | Non-root User `app`, `--workers 1 --proxy-headers --forwarded-allow-ips='*'` |
| `frontend/Dockerfile` | B2 | `ARG VITE_API_URL=""`, `nginx:1.27-alpine` gepinnt |
| `frontend/nginx.conf` | B2 | `client_max_body_size 20m`, `proxy_read_timeout 86400`, Cache-Headers |
| `backend/app/core/config.py` | C3 | Neues Feld `environment: str = "development"` |
| `backend/app/main.py` | C2+C3 | Health-Endpoint mit DB-Check (SELECT 1, 503), Startup-Log |
| `backend/app/core/rate_limit.py` | C1 | Dokumentations-Kommentar zu Proxy-Kette |
| `frontend/src/api/client.ts` | D | `export const API_BASE`, `baseURL: API_BASE` |
| `frontend/src/stores/auth.ts` | D | `API_BASE` statt `import.meta.env.VITE_API_URL` (2 Stellen) |
| `frontend/src/composables/useSocket.ts` | D | `API_BASE \|\| undefined` für same-origin Fallback |
| `frontend/src/env.d.ts` | D | `VITE_API_URL?: string` (optional) |
| `.env.example` | A2 | Auth-Variablen ergänzt |
| `.gitignore` | A2 | `.env.prod` ignoriert, `!.env.prod.example` committed |
| `scripts/backup-db.ps1` | E | Parameter: `-ComposeFile`, `-EnvFile`, `-ProjectName` |
| `scripts/restore-db.ps1` | E | Parameter: `-ComposeFile`, `-EnvFile`, `-ProjectName` |

## Acceptance Criteria Mapping

| # | Kriterium | Status | Methode |
|---|-----------|--------|---------|
| 1 | `docker compose -f docker-compose.prod.yml` startet 3 Container healthy, Logs zeigen Alembic + C3-Startup, keine Ports für postgres/backend | **code-traced** | `docker-compose.prod.yml` hat keine `ports:` für postgres/backend; Healthchecks konfiguriert; `backend/Dockerfile` CMD enthält `alembic upgrade head`; `main.py` lifespan loggt Env-Info |
| 2 | Login, F5 hält Session, nach 16min funktioniert Action (Refresh same-origin) | **user-verified** | `auth.ts` nutzt `API_BASE` (leer = same-origin); `client.ts` Interceptor refresht bei 401 |
| 3 | Socket.IO Status 101 (WebSocket), Echtzeit-Sync | **user-verified** | `nginx.conf` hat WebSocket-Upgrade + `proxy_read_timeout 86400`; `useSocket.ts` nutzt `API_BASE \|\| undefined` |
| 4 | `/api/health` → `db: true`; Postgres stop → 503 | **code-traced** | `main.py` Health-Endpoint führt `SELECT 1` aus, fängt Exception → 503 |
| 5 | 5 falsche Logins → 429; anderes Gerät kann noch einloggen | **user-verified** | `rate_limit.py` nutzt `get_remote_address`; `--proxy-headers` in Dockerfile; Test `test_rate_limit_proxy.py` bestätigt separate Buckets |
| 6 | `backup-db.ps1` gegen Prod erzeugt Dump; Restore in Throwaway funktioniert | **user-verified** | Skripte parametrisiert mit `-ComposeFile`, `-EnvFile`, `-ProjectName` |
| 7 | Placeholder JWT_SECRET_KEY → lesbarer Startup-Fehler | **code-traced** | `main.py` lifespan prüft `_JWT_PLACEHOLDER` und `len < 32` → `RuntimeError` |
| 8 | Backend-Tests bestehen inkl. C1-Test; vue-tsc + check:locales bestehen | **executed** | 347 Tests passed; vue-tsc exit 0; 617 Locale-Keys in sync |
