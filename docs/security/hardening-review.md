# 🔒 Security Review — Hardening: Tokens, HTTP-Header, Rate-Limits, Dependencies

**Datum:** 2026-10-05
**Reviewer:** Security-Review Agent
**Status:** ✅ Umgesetzt (Header, CORS, Rate-Limits, Upload-Formate, CI-Audit) — ⚠️ offen: Token-Storage (Vorschlag). Dependency-Updates (H-10) sind seit #14 eingespielt, H-11 seit #8 behoben (Stand 2026-10-06)
**Branch:** `claude/security-hardening`
**Scope:** Auth-Token-Lifecycle, HTTP-Security-Header + CORS, Rate-Limiting, Dependency-Audit

---

## Geprüfte Dateien

| Datei | Bereich |
|---|---|
| `backend/app/core/security.py` | JWT-Erzeugung/-Validierung, Refresh-Token-Hashing |
| `backend/app/routers/auth.py` | Login, Register, Refresh (Rotation + Reuse-Detection), Logout |
| `backend/app/core/deps.py` | `get_current_user` |
| `backend/app/core/rate_limit.py` | slowapi-Limiter |
| `backend/app/routers/households.py` | Join per Invite-Code, Invite-Code abrufen |
| `backend/app/routers/files.py` | Bildverarbeitung (Pillow) |
| `backend/app/main.py` | CORS, Middleware |
| `backend/app/socket_manager.py` | Socket.IO-Auth, Engine.IO-CORS |
| `backend/Dockerfile` | uvicorn `--proxy-headers`, Worker-Anzahl |
| `frontend/nginx.conf` | Statische Auslieferung, Reverse-Proxy |
| `frontend/src/services/tokenStorage.ts` | Token-Persistenz (localStorage) |
| `frontend/src/stores/auth.ts`, `frontend/src/api/client.ts` | Refresh-Flow, Interceptors |
| `frontend/vite.config.ts`, `frontend/public/push-sw.js` | PWA / Service Worker |
| `.github/workflows/ci.yml` | CI |

---

## Zusammenfassung

| # | Schweregrad | Finding | Status |
|---|---|---|---|
| H-01 | 🟡 Mittel | Refresh-Token (30 Tage) liegt in `localStorage` → per XSS exfiltrierbar | 📝 Vorschlag (siehe unten) |
| H-02 | 🟡 Mittel | Keine HTTP-Security-Header (CSP, nosniff, Frame-Schutz, Referrer-Policy) — weder nginx noch API | ✅ Behoben |
| H-03 | 🟢 Gering | CORS: `allow_credentials=True` + `allow_methods/headers=["*"]`, obwohl keine Cookies verwendet werden | ✅ Behoben |
| H-04 | 🟡 Mittel | `POST /api/households/join` ohne Rate-Limit → Invite-Code-Brute-Force | ✅ Behoben |
| H-05 | 🟢 Gering | `/api/auth/refresh` und `/api/auth/logout` ohne Rate-Limit | ✅ Behoben |
| H-06 | 🟢 Gering | Login: Timing verrät, ob eine E-Mail registriert ist (bcrypt nur bei existierendem User) | ✅ Behoben |
| H-07 | 🟢 Gering | JWT-Validierung erzwingt `exp`/`sub` nicht explizit | ✅ Behoben |
| H-08 | 🟡 Mittel | Pillow dekodiert jedes bekannte Format, obwohl nur JPEG/PNG/WEBP erlaubt sind (MIME kommt vom Client) | ✅ Behoben |
| H-09 | 🟢 Gering | `GET /recurring-bills` ohne Trailing-Slash → 307 auf absolute `http://`-URL (Mixed Content / CSP-Block) | ✅ Behoben |
| H-10 | 🟡 Mittel | Dependencies mit bekannten Advisories (Pillow, PyJWT, urllib3, cryptography, axios, …) | ✅ Behoben mit #14 (Updates), CI-Audit-Job aktiv |
| H-11 | 🟢 Gering | nginx überschreibt `X-Forwarded-Proto` mit `$scheme` (= `http` hinter NPM) | ✅ Behoben mit #8 |
| H-12 | 🟢 Gering | Invite-Codes laufen nie ab / nicht rotierbar | 📝 Offen |
| H-13 | ℹ️ Info | Rate-Limits nur per IP, In-Memory-Storage (Reset bei Neustart) | Akzeptiert (1 Worker) |
| H-14 | ℹ️ Info | Upload-Endpoint weiterhin ohne Rate-Limit (vgl. Epic 8 F-06) | 📝 Offen |
| H-15 | 🟢 Gering | Socket-Verbindungen bleiben nach Logout und Ablauf des Access-Tokens unbegrenzt offen | ✅ Behoben (Nachtrag unten) |

---

## 1. Auth-Tokens

### Ist-Zustand (bereits gut)

Die geforderten **kurzlebigen Access-Tokens mit Refresh-Token-Rotation existieren bereits** (Epic 12/12b):

- Access-Token: JWT HS256, **15 Minuten** (`ACCESS_TOKEN_EXPIRE_MINUTES`), Secret-Länge ≥ 32 wird beim Start erzwungen (`main.py` lifespan).
- Refresh-Token: opak (`secrets.token_urlsafe(32)`), in der DB nur als **SHA-256-Hash** (`refresh_tokens.token_hash`), 30 Tage gültig.
- **Rotation** bei jedem `/refresh`, `replaced_by_id`-Kette, **Reuse-Detection** (Wiederverwendung eines rotierten Tokens revoked alle Tokens des Users) mit 30-s-Grace-Window für parallele Tabs.
- Logout revoked serverseitig; Lazy-Cleanup abgelaufener Tokens.
- Frontend: Single-Flight-Refresh, Cross-Tab-Sync über `storage`-Event.

Eine Neuimplementierung war daher nicht nötig. Ergänzt wurde (H-05/H-06/H-07):

- `/refresh` und `/logout` sind rate-limitiert (30/min/IP).
- Login führt bei unbekannter E-Mail einen Dummy-bcrypt-Vergleich durch → keine Account-Enumeration über die Antwortzeit.
- `decode_access_token` verlangt `exp` und `sub` (`options={"require": [...]}`); `alg=none` ist durch `algorithms=["HS256"]` ausgeschlossen (Test vorhanden).
- Alle `/api/auth/*`-Responses tragen `Cache-Control: no-store`.

### Nachtrag H-15 — Token-Ablauf auf Socket-Verbindungen (✅ Behoben)

**Vorher:** `socket_manager.connect` prüfte das Access-Token nur beim Verbindungsaufbau. Danach empfing die Verbindung Haushalts-Events, solange sie offen war, auch nach `/logout`, nach der Reuse-Detection und lange nach Ablauf des Tokens.

**Jetzt:**
- Der Server speichert `exp` in der Socket-Session und trennt die Verbindung per Timer bei Ablauf (`session_ended` mit Grund `expired`). `join_household` prüft `exp` zusätzlich.
- Der Client verlängert nach jedem Token-Refresh mit `reauth {token}`; der Server akzeptiert nur ein gültiges Token desselben Users, sonst bleibt der alte Ablauf.
- `/api/auth/logout` (Grund `logout`) und die Reuse-Detection in `/refresh` (Grund `revoked`) trennen alle Verbindungen des Users über den persönlichen Raum (`disconnect_user_sync`, gleicher Sync/Async-Übergang wie `emit_to_household_sync`).
- Der Client refresht nach `logout`/`revoked` bewusst nicht (Gefahr: Refresh mit gerade widerrufenem Token → Reuse-Detection → alle Geräte abgemeldet), sondern verbindet nur mit seinem aktuellen Access-Token neu.

**Restrisiko:** Ein gestohlenes Access-Token erlaubt bis zu seinem Ablauf (max. 15 Min.) neue Verbindungen, wie bei der REST-API. Gezieltes Trennen nur des ausloggenden Geräts bräuchte eine Sitzungs-Kennung im Token (siehe `family_id`-Vorschlag unter H-01).

Tests: `backend/tests/test_socket_session.py` (Ablauf, `reauth`, Raumbeitritt nach Ablauf, Logout, Reuse-Detection), `frontend/src/composables/__tests__/useSocket.test.ts`, `frontend/src/stores/__tests__/auth.test.ts` (`refreshForSocket`, Socket-Trennung vor Logout).

### Nachtrag H-02 — CSP und PDF-Vorschau (Dokument-Ablage)

Beim Zusammenführen mit der Dokument-Ablage (`DocumentsView.vue`) zeigte sich im Browser (Chromium, gebautes Frontend, Header aus `frontend/nginx/security-headers.conf`):

- Die PDF-Vorschau ist ein `<iframe>` auf eine Blob-URL. Ohne `frame-src` greift `default-src 'self'`, das `blob:` nicht erlaubt → `Refused to frame 'blob:…'`. **Behoben:** `frame-src blob:`.
- Der PDF-Betrachter im Blob-Dokument erbt die CSP der Seite; seine Inline-Styles wurden blockiert, die Ansicht kollabierte auf einen schmalen Streifen. **Behoben:** `style-src-attr 'unsafe-inline'` (nur `style=""`-Attribute; `<style>`-Blöcke und externe CSS bleiben durch `style-src 'self'` gesperrt).
- Bekannte Einschränkung: In der Werkzeugleiste des eingebetteten Betrachters fehlen unter der CSP die Schaltflächen „Drucken" und „Mehr". Die Ursache liegt nicht an Styles (auch mit `style-src 'unsafe-inline'` fehlen sie). Die App bietet einen eigenen Download-Button. Nicht weiter untersucht.
- Geprüft wurden nur `/documents` (inkl. Vorschau) und `/shopping`; weitere Seiten wurden nicht gegen die CSP getestet.

### H-01 — Refresh-Token in `localStorage` (🟡 Mittel, Vorschlag)

**Risiko:** Jedes XSS kann `localStorage.haushalt_tokens` lesen und erhält damit einen **30 Tage gültigen** Refresh-Token, der auch nach Schliessen des Tabs weiter rotiert werden kann. Die Reuse-Detection greift erst, wenn der legitime Client den gestohlenen (bereits rotierten) Token erneut benutzt — der Angreifer kann also bis zur nächsten Rotation durch den Nutzer weiterarbeiten.

**Mitigation durch diesen Branch:** Die neue strikte CSP (`script-src 'self'`, kein `unsafe-inline`/`unsafe-eval`) macht XSS deutlich schwerer ausnutzbar — sie ist die wichtigste Verteidigung, solange Tokens in JS-zugänglichem Storage liegen.

**Warum nicht in diesem Branch umgesetzt:** Ein HttpOnly-Cookie ändert den Vertrag von `/login`, `/register`, `/refresh` und `/logout`, erfordert CSRF-Schutz, berührt Auth-Store, API-Client, Cross-Tab-Sync, alle Auth-Tests (Backend + Frontend) und kollidiert mit dem geplanten Capacitor-Build (`tokenStorage.ts`-TODO: SecureStorage, dort gibt es keine Cookies im gleichen Sinn). Ein halber Umbau wäre schlechter als der jetzige, konsistente Zustand.

**Konkreter Vorschlag (Web-Build), abwärtskompatibel in zwei Releases:**

1. **Backend (Release 1, additiv):**
   - `_create_token_pair` setzt zusätzlich `Set-Cookie: casa_rt=<refresh>; HttpOnly; Secure; SameSite=Strict; Path=/api/auth; Max-Age=2592000`.
   - `/refresh` und `/logout` akzeptieren den Token **aus dem Body ODER dem Cookie** (Body hat Vorrang → native Clients unverändert). `RefreshRequest.refresh_token` wird optional.
   - CSRF: `SameSite=Strict` + Pfad `/api/auth` + Pflicht-Header `X-Requested-With: casa` (nicht CORS-safelisted → erzwingt Preflight, den fremde Origins nicht bestehen) für Cookie-basierte Requests. Für Cross-Origin-Dev (`VITE_API_URL`) müsste `allow_credentials=True` wieder aktiviert werden — Empfehlung: Dev über den Vite-Proxy (same-origin) laufen lassen.
   - `/logout` löscht den Cookie (`Max-Age=0`).
   - Tests: Cookie gesetzt (Flags!), Refresh nur per Cookie, Body-Refresh weiterhin möglich, Refresh ohne Pflicht-Header → 403, Logout löscht Cookie.
2. **Frontend (Release 2):**
   - `TokenStorage`-Interface behalten; neue Web-Implementierung `MemoryAccessTokenStorage`: Access-Token nur im Speicher, `refreshToken` = Platzhalter, kein `localStorage` mehr.
   - Boot: `initialize()` ruft immer `/refresh` (Cookie) statt Tokens aus `localStorage` zu lesen.
   - Cross-Tab: `storage`-Event durch `BroadcastChannel('casa-auth')` (logout/refreshed) ersetzen.
   - Einmalige Migration: vorhandenen `haushalt_tokens`-Eintrag beim ersten Start per Body-Refresh gegen Cookie tauschen, dann löschen.
   - Capacitor: bestehende Body-Variante + SecureStorage-Implementierung des Interfaces.
3. **Release 3:** Body-Variante für Web-Origin deaktivieren (optional, nur wenn kein nativer Client mehr Body nutzt).

**Aufwand:** ca. 1–1.5 Tage inkl. Tests. Keine Alembic-Migration nötig (Tabelle `refresh_tokens` bleibt unverändert).

**Weitere Empfehlungen Token-Lifecycle:**
- Absolute Session-Obergrenze: derzeit verlängert jede Rotation die Laufzeit um 30 Tage (Sliding Window). Ein `session_started_at`/`family_id` auf `refresh_tokens` (Alembic-Migration) würde eine Höchstdauer (z. B. 90 Tage) und gezieltes Revoken einer Session-Familie statt *aller* Sessions erlauben.
- Sobald es Passwort-Ändern/-Reset gibt: dort alle Refresh-Tokens des Users revoken.

---

## 2. HTTP-Security-Header & CORS

### H-02 — Security-Header (✅ Behoben)

**API (Backend):** neue reine ASGI-Middleware `app/core/security_headers.py` (kein `BaseHTTPMiddleware` → Streaming/FileResponse und Socket.IO-Mount unverändert; WebSockets werden nicht angefasst). Gilt auch für 401/404/429 und CORS-Preflights:

| Header | Wert | Begründung |
|---|---|---|
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'` | API liefert nie renderbares HTML; schützt auch `inline`-ausgelieferte Uploads. Ausnahme `/docs`, `/redoc`, `/openapi.json` (Swagger lädt vom CDN). |
| `X-Content-Type-Options` | `nosniff` | Kein MIME-Sniffing von Uploads |
| `X-Frame-Options` | `DENY` | Clickjacking (Legacy-Browser) |
| `Referrer-Policy` | `no-referrer` | |
| `Cross-Origin-Opener-Policy` | `same-origin` | |
| `Cross-Origin-Resource-Policy` | `same-origin` | Uploads nicht per `<img>` von Fremdseiten einbettbar |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=(), usb=()` | |
| `Cache-Control` | `no-store` (nur `/api/auth/*`) | Tokens nicht in Caches |

**SPA (nginx):** neues Snippet `frontend/nginx/security-headers.conf`, per `include` in **jeder** statischen `location` mit eigenem `add_header` eingebunden (nginx vererbt `add_header` sonst nicht). `/api/` und `/socket.io/` binden es bewusst nicht ein (Header kommen vom Backend, keine Duplikate). Zusätzlich `server_tokens off`.

```
default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:;
font-src 'self'; connect-src 'self' wss://$host; worker-src 'self'; manifest-src 'self';
object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'
```

- Kein `'unsafe-inline'`/`'unsafe-eval'`: Der Vite-Build enthält keine Inline-Skripte und kein `eval`/`new Function` (geprüft im `dist/`); vue-i18n nutzt den JIT-Compiler. Statische `style="…"`-Attribute in Templates werden von Vue über das CSSOM gesetzt und fallen nicht unter `style-src`.
- `img-src blob:` für Datei-/Tierfotos (`URL.createObjectURL`), `data:` für kleine eingebettete Assets.
- `wss://$host` explizit, weil ältere Safari-Versionen `'self'` nicht auf WebSockets anwenden.
- Kein `upgrade-insecure-requests`: würde lokale HTTP-Deployments (`http://localhost:8080`) brechen.
- **HSTS** gehört an den TLS-Terminator (Nginx Proxy Manager → „HSTS enabled"), nicht in diesen Container, der nur HTTP spricht.
- **Einschränkung:** Bei einem Build mit `VITE_API_URL` auf einen anderen Origin muss `connect-src` um diesen Origin ergänzt werden.

**Verifikation:** Produktions-Build (`vite build`) mit der echten `nginx.conf` + Snippet (`nginx -t` ok) vor einem lokalen Backend ausgeliefert und mit headless Chromium (Playwright) durchgeklickt: Login über das UI, alle Routen (`/dashboard`, `/shopping`, `/todos`, `/expenses`, `/chores`, `/calendar`, `/pets`, `/food`, `/notes`, `/household`), Blob-Bild, Manifest. Ergebnis: **0 CSP-Violations, keine Console-Errors**, Service Worker (`/sw.js` inkl. `importScripts('/push-sw.js')`) aktiv, Socket.IO verbindet per WebSocket. Push-Nachrichten selbst laufen über den Push-Dienst des Browsers und unterliegen nicht der Seiten-CSP.

### H-09 — Redirect auf absolute HTTP-URL (✅ Behoben)

Der CSP-Test fand genau einen Verstoss: `GET /api/households/{id}/recurring-bills` (ohne Slash) → FastAPI-307 auf `http://<host>/…/recurring-bills/`. Hinter NPM wäre das von einer HTTPS-Seite aus Mixed Content (also schon vorher kaputt bzw. vom Browser blockiert), mit CSP wird es zusätzlich geblockt. Fix: `financeRepository.ts` ruft `…/recurring-bills/` direkt auf (GET + POST). Alle anderen Repositories nutzen bereits den kanonischen Pfad (Backend-Log zeigte keine weiteren 307).

### H-11 — `X-Forwarded-Proto` (✅ Behoben mit #8)

**Nachtrag 2026-10-06:** `frontend/nginx.conf` reicht den Header seit #8 über `map $http_x_forwarded_proto $forwarded_proto` (Fallback `$scheme`) durch. Der folgende Text beschreibt den Zustand vor #8.

`nginx.conf` setzt `X-Forwarded-Proto $scheme`; hinter NPM ist das `http`. uvicorn (`--proxy-headers`) hält die Requests daher für HTTP und erzeugt `http://`-Redirect-URLs (Ursache von H-09). Empfehlung: in `location /api/` und `/socket.io/` den Header von NPM durchreichen (`map $http_x_forwarded_proto $fwd_proto { default $http_x_forwarded_proto; "" $scheme; }`) — nicht in diesem Branch geändert, weil es das Deployment-Setup betrifft und lokal nicht verifizierbar ist.

### H-03 — CORS (✅ Behoben)

- `allow_credentials=False`: Auth läuft ausschliesslich über den `Authorization`-Header, es gibt keine Cookies. (Beim Cookie-Vorschlag aus H-01 wieder zu prüfen.)
- `allow_methods` explizit (`GET, POST, PUT, PATCH, DELETE, OPTIONS`), `allow_headers` explizit (`Authorization, Content-Type, Accept, Accept-Language`).
- Produktion ist same-origin (nginx-Proxy), CORS greift nur im Dev-Setup. Socket.IO: Engine.IO-CORS ist deaktiviert und läuft über dieselbe Middleware — unverändert korrekt.
- Tests: erlaubter Origin, fremder Origin, unbekannter Header, kein `Access-Control-Allow-Credentials`.

---

## 3. Rate-Limiting

| Endpoint | Vorher | Nachher |
|---|---|---|
| `POST /api/auth/login` | 5/min | 5/min |
| `POST /api/auth/register` (inkl. Beitritt per Invite-Code) | 3/h | 3/h |
| `POST /api/auth/refresh` | – | **30/min** |
| `POST /api/auth/logout` | – | **30/min** |
| `POST /api/households/join` | – | **5/min; 20/h** |
| `GET /api/households/{id}/invite-code` | – | – (nur für Mitglieder, liest nur den eigenen Code) |
| `POST /api/push/subscribe` | 5/min | 5/min |

**H-04:** Invite-Codes haben 8 Zeichen aus 32 Symbolen (≈ 2⁴⁰). Ohne Limit konnte ein eingeloggter User beliebig schnell raten; jetzt max. 20 Versuche/h/IP. `register` mit `invite_code` war bereits über 3/h abgedeckt.

Die Limits von `refresh` sind so gewählt, dass mehrere Geräte hinter einem NAT (Haushalt!) mit 15-min-Access-Tokens weit darunter bleiben. Ein 429 auf `/refresh` führt im Frontend zum Logout (Interceptor-`catch`) — bei 30/min praktisch nicht erreichbar.

**H-13 (Info):** slowapi zählt per Client-IP im Prozessspeicher. Das ist korrekt, solange uvicorn mit `--workers 1` läuft (durch Socket.IO ohnehin erzwungen) und `--proxy-headers` die echte IP liefert (`test_rate_limit_proxy.py`). Es gibt keinen Per-Account-Lockout; ein verteilter Angriff auf ein Konto wird nur per IP gebremst. Empfehlung bei Bedarf: zusätzliches Limit per `form_data.username` (eigene `key_func`) und Redis-Storage bei Skalierung.

**H-12 (Offen):** Invite-Codes sind permanent. Empfehlung: Admin-Endpoint „Code neu generieren" (+ Rate-Limit), optional Ablaufdatum.

**H-14 (Offen):** Upload (`POST /files/`) hat weiterhin kein Rate-Limit/Quota (Epic 8, F-06).

### H-08 — Pillow-Formate (✅ Behoben)

`_process_image` öffnet Bilder jetzt mit `Image.open(..., formats=("JPEG", "PNG", "WEBP"))`. Vorher entschied nur der vom Client gesendete MIME-Typ; eine als `image/png` deklarierte PSD-/FITS-/GD-/PDF-Datei wäre von dem jeweiligen Pillow-Decoder geparst worden — genau dort liegen mehrere der offenen Pillow-Advisories (H-10). Test: GIF/BMP/TIFF als `image/png` → 422.

---

## 4. Dependency-Audit

Neuer CI-Job `dependency-audit` in `.github/workflows/ci.yml`: eigener Job ohne `needs`, blockiert `backend`/`frontend` nicht. Beide Audits laufen immer (`continue-on-error`), ein abschliessender Schritt macht den Job rot, wenn einer Befunde hat. Zum Zeitpunkt dieses Reviews war der Job rot (Befunde unten). **Nachtrag 2026-10-06:** Nach den Updates aus #14 meldet er keine Befunde mehr und läuft grün; ob er als Required Check konfiguriert wird, ist eine GitHub-Einstellung des Repositorys.

### H-10 — Befunde (Stand 2026-10-05, nicht blind aktualisiert)

**Backend — `pip-audit -r backend/requirements.txt`**

| Paket | Version | Fix | Advisories | Relevanz für Casa |
|---|---|---|---|---|
| Pillow | 11.2.1 | 12.3.0 | ~20 (u. a. PSD/FITS/GD/PCF/BDF-Decoder, PdfParser-DoS, Heap-Overflow beim Schreiben grosser Bilder, Koordinaten-APIs) | **Hoch** — verarbeitet Nutzer-Uploads. Durch H-08 sind die Decoder-Advisories für PSD/FITS/GD/PDF/Fonts nicht mehr erreichbar (PYSEC-2025-61 betrifft das DDS-Schreiben, Casa speichert nur JPEG/PNG). Restrisiko bleibt in den JPEG/PNG/WEBP-Decodern und den Koordinaten-/Filter-APIs. **Update trotzdem priorisieren** (Major-Sprung 11→12, Upload-Tests laufen lassen). |
| PyJWT | 2.13.0 | 2.14.0 / 2.15.0 | 13 (JWKS-Client, PEM/RSA, Alg-Confusion bei gemischten Key-Typen, nicht-Base64url-Signaturen, `options`-Mutation) | **Gering** — nur HS256 mit statischem Secret, kein JWKS, kein asymmetrischer Key, `options` wird pro Aufruf neu erzeugt. Trotzdem auf 2.15.0 heben (Patch/Minor). |
| urllib3 | 2.7.0 | 2.8.0 | 3 (Streaming-API, HTTPS-Proxy-TLS) | **Gering** — nur indirekt via `requests`/`pywebpush` für ausgehende Push-Requests. Minor-Update. |
| cryptography | 49.0.0 | 50.0.0 | 1 (PKCS#7-Decrypt-Orakel) | **Keine** — PKCS#7-Decrypt wird nicht verwendet (nur VAPID/ECDH via py-vapid/http_ece). Mit nächstem Routine-Update. |

**Frontend — `npm audit --omit=dev --audit-level=high`**

| Paket | Version | Fix | Schwere | Relevanz |
|---|---|---|---|---|
| axios | 1.19.0 (direkt) | ≥ 1.20.0 | high | **Mittel** — die meisten Advisories betreffen den Node-HTTP/HTTP2-Adapter, Proxy-Handling oder Prototype-Pollution-Gadgets (setzen eine separate Pollution-Lücke voraus). Im Browser wird der XHR-Adapter genutzt. Update ist ein Minor → empfohlen. |
| nanoid | 3.3.16 (via vite → postcss) | ≥ 3.3.18 | high | **Keine zur Laufzeit** — Build-Tool-Kette; wird trotz `--omit=dev` gemeldet. `npm audit fix` (Lockfile-only). |
| brace-expansion | 2.0.0–2.1.6 (transitiv) | `npm audit fix` | high | Dev-Tooling, keine Laufzeitrelevanz |
| vitest / @vitest/mocker | ≤ 4.1.10 | neuere 4.1.x | moderate | Nur Testumgebung |

---

## Neue/geänderte Tests

`backend/tests/test_security_hardening.py` (25 Tests):
- Security-Header auf 200/401/429, keine API-CSP auf `/docs`, `no-store` auf Auth-Responses
- CORS: erlaubter/fremder Origin, unbekannter Header, keine Credentials
- Rate-Limit registriert auf login/register/refresh/logout/join; Verhalten (429 + `RATE_LIMITED`) für join, refresh, logout
- JWT ohne `exp`, ohne `sub`, `alg=none` → 401
- Login mit unbekannter E-Mail führt Passwort-Vergleich aus
- Upload: GIF/BMP/TIFF als `image/png` → 422

---

## Gesamtbewertung

Die Auth-Architektur (kurzlebige JWTs, gehashte opake Refresh-Tokens, Rotation mit Reuse-Detection) ist solide und war bereits umgesetzt. Die grössten Lücken lagen in fehlenden HTTP-Security-Headern und einem ungeschützten Join-Endpoint — beides ist behoben, und die strikte CSP verringert das Hauptrisiko des localStorage-Token-Storage erheblich.

**Als Nächstes empfohlen (Reihenfolge):**
1. ✅ **Umgesetzt mit #14:** Pillow 12.3.0, PyJWT 2.15.0, urllib3 2.8.0, Werkzeug 3.1.9, multidict 6.9.1, cryptography 50.0.0 sowie `npm audit fix` (axios 1.20.0 u. a.). Offen: `dependency-audit` als Required Check einstellen.
2. **H-01:** HttpOnly-Refresh-Cookie gemäss Vorschlag oben (2 Releases).
3. ✅ **H-11** durch #8 behoben. Offen: HSTS in NPM aktivieren.
4. **H-12/H-14:** Invite-Code-Rotation, Upload-Rate-Limit/Quota.
5. CSP-Monitoring: optional `report-to`-Endpoint, um Violations aus dem Feld zu sehen.
