# 🔒 Security Review — Hardening: Tokens, HTTP-Header, Rate-Limits, Dependencies

**Datum:** 2026-10-05
**Reviewer:** Security-Review Agent
**Status:** ✅ Umgesetzt (Header, CORS, Rate-Limits, Upload-Formate, CI-Audit). Dependency-Updates (H-10) sind seit #14 eingespielt, H-11 seit #8 behoben, H-01 (Refresh-Token als HttpOnly-Cookie) mit Branch `claude/refresh-token-httponly-cookie` (Stand 2026-10-06)
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
| `frontend/src/services/tokenStorage.ts` | Token-Persistenz (localStorage; seit H-01 nur Sitzungs-Marker + Migration) |
| `frontend/src/stores/auth.ts`, `frontend/src/api/client.ts` | Refresh-Flow, Interceptors |
| `frontend/vite.config.ts`, `frontend/public/push-sw.js` | PWA / Service Worker |
| `.github/workflows/ci.yml` | CI |

---

## Zusammenfassung

| # | Schweregrad | Finding | Status |
|---|---|---|---|
| H-01 | 🟡 Mittel | Refresh-Token (30 Tage) liegt in `localStorage` → per XSS exfiltrierbar | ✅ Behoben (HttpOnly-Cookie + CSRF-Header, siehe unten) |
| H-02 | 🟡 Mittel | Keine HTTP-Security-Header (CSP, nosniff, Frame-Schutz, Referrer-Policy) — weder nginx noch API | ✅ Behoben |
| H-03 | 🟢 Gering | CORS: `allow_credentials=True` + `allow_methods/headers=["*"]`, obwohl keine Cookies verwendet werden | ✅ Behoben; mit H-01 wieder `allow_credentials=True`, aber nur für explizite Origins (Startup-Check gegen `*`) |
| H-04 | 🟡 Mittel | `POST /api/households/join` ohne Rate-Limit → Invite-Code-Brute-Force | ✅ Behoben |
| H-05 | 🟢 Gering | `/api/auth/refresh` und `/api/auth/logout` ohne Rate-Limit | ✅ Behoben |
| H-06 | 🟢 Gering | Login: Timing verrät, ob eine E-Mail registriert ist (bcrypt nur bei existierendem User) | ✅ Behoben |
| H-07 | 🟢 Gering | JWT-Validierung erzwingt `exp`/`sub` nicht explizit | ✅ Behoben |
| H-08 | 🟡 Mittel | Pillow dekodiert jedes bekannte Format, obwohl nur JPEG/PNG/WEBP erlaubt sind (MIME kommt vom Client) | ✅ Behoben |
| H-09 | 🟢 Gering | `GET /recurring-bills` ohne Trailing-Slash → 307 auf absolute `http://`-URL (Mixed Content / CSP-Block) | ✅ Behoben |
| H-10 | 🟡 Mittel | Dependencies mit bekannten Advisories (Pillow, PyJWT, urllib3, cryptography, axios, …) | ✅ Behoben mit #14 (Updates), CI-Audit-Job aktiv |
| H-11 | 🟢 Gering | nginx überschreibt `X-Forwarded-Proto` mit `$scheme` (= `http` hinter NPM) | ✅ Behoben mit #8 |
| H-12 | 🟢 Gering | Invite-Codes laufen nie ab / nicht rotierbar | ✅ Behoben |
| H-13 | ℹ️ Info | Rate-Limits nur per IP, In-Memory-Storage (Reset bei Neustart) | Akzeptiert (1 Worker) |
| H-14 | ℹ️ Info | Upload-Endpoint ohne Rate-Limit (vgl. Epic 8 F-06) | ✅ Behoben (`30/minute;300/hour`) |

---

## 1. Auth-Tokens

### Ist-Zustand (bereits gut)

Die geforderten **kurzlebigen Access-Tokens mit Refresh-Token-Rotation existieren bereits** (Epic 12/12b):

- Access-Token: JWT HS256, **15 Minuten** (`ACCESS_TOKEN_EXPIRE_MINUTES`), Secret-Länge ≥ 32 wird beim Start erzwungen (`main.py` lifespan).
- Refresh-Token: opak (`secrets.token_urlsafe(32)`), in der DB nur als **SHA-256-Hash** (`refresh_tokens.token_hash`), 30 Tage gültig.
- **Rotation** bei jedem `/refresh`, `replaced_by_id`-Kette, **Reuse-Detection** (Wiederverwendung eines rotierten Tokens revoked alle Tokens des Users) mit 30-s-Grace-Window für parallele Tabs.
- Logout revoked serverseitig; Lazy-Cleanup abgelaufener Tokens.
- Frontend: Single-Flight-Refresh, Cross-Tab-Sync über `storage`-Event.
- Seit H-01: Refresh-Token im Web-Build als HttpOnly-Cookie (siehe unten), Access-Token nur im Speicher.

Eine Neuimplementierung war daher nicht nötig. Ergänzt wurde (H-05/H-06/H-07):

- `/refresh` und `/logout` sind rate-limitiert (30/min/IP).
- Login führt bei unbekannter E-Mail einen Dummy-bcrypt-Vergleich durch → keine Account-Enumeration über die Antwortzeit.
- `decode_access_token` verlangt `exp` und `sub` (`options={"require": [...]}`); `alg=none` ist durch `algorithms=["HS256"]` ausgeschlossen (Test vorhanden).
- Alle `/api/auth/*`-Responses tragen `Cache-Control: no-store`.

### Nachtrag H-02 — CSP und PDF-Vorschau (Dokument-Ablage)

Beim Zusammenführen mit der Dokument-Ablage (`DocumentsView.vue`) zeigte sich im Browser (Chromium, gebautes Frontend, Header aus `frontend/nginx/security-headers.conf`):

- Die PDF-Vorschau ist ein `<iframe>` auf eine Blob-URL. Ohne `frame-src` greift `default-src 'self'`, das `blob:` nicht erlaubt → `Refused to frame 'blob:…'`. **Behoben:** `frame-src blob:`.
- Der PDF-Betrachter im Blob-Dokument erbt die CSP der Seite; seine Inline-Styles wurden blockiert, die Ansicht kollabierte auf einen schmalen Streifen. **Behoben:** `style-src-attr 'unsafe-inline'` (nur `style=""`-Attribute; `<style>`-Blöcke und externe CSS bleiben durch `style-src 'self'` gesperrt).
- Bekannte Einschränkung: In der Werkzeugleiste des eingebetteten Betrachters fehlen unter der CSP die Schaltflächen „Drucken" und „Mehr". Die Ursache liegt nicht an Styles (auch mit `style-src 'unsafe-inline'` fehlen sie). Die App bietet einen eigenen Download-Button. Nicht weiter untersucht.
- Geprüft wurden nur `/documents` (inkl. Vorschau) und `/shopping`; weitere Seiten wurden nicht gegen die CSP getestet.

### H-01 — Refresh-Token in `localStorage` (🟡 Mittel, ✅ Behoben)

**Risiko (vorher):** Jedes XSS konnte `localStorage.haushalt_tokens` lesen und erhielt damit einen **30 Tage gültigen** Refresh-Token, der auch nach Schliessen des Tabs weiter rotiert werden konnte. Die Reuse-Detection griff erst, wenn der legitime Client den gestohlenen (bereits rotierten) Token erneut benutzte.

**Umsetzung (Branch `claude/refresh-token-httponly-cookie`, Web-PWA):**

*Backend (`backend/app/routers/auth.py`)*

- Der Web-Client weist sich bei allen Auth-Requests mit dem Header **`X-Requested-With: casa`** aus. Nur dann liefert das Backend den Refresh-Token als Cookie **`casa_rt`** mit `HttpOnly; SameSite=Strict; Path=/api/auth; Max-Age=<REFRESH_TOKEN_EXPIRE_DAYS>` und `Secure` in Produktion (`ENVIRONMENT=production`, überschreibbar per `AUTH_COOKIE_SECURE`). Der Body enthält dann `refresh_token: null`; der **Access-Token bleibt im Body** und wird weiter als `Authorization: Bearer` gesendet (auch für Socket.IO `auth.token`).
- `/refresh` und `/logout` lesen den Token **aus dem Body (Vorrang) oder dem Cookie**. `RefreshRequest.refresh_token`/`LogoutRequest.refresh_token` sind optional, ein leerer Body genügt. Rotation, `replaced_by_id`-Kette, Grace-Window und Reuse-Detection sind unverändert; sie laufen auf demselben Hash wie vorher.
- Jede 401-Antwort auf einen Cookie-Refresh (ungültig, abgelaufen, Reuse) und jeder Logout löschen den Cookie (`Max-Age=0`), damit der Browser keinen toten Token mehr mitschickt.
- Clients **ohne** den Header (Swagger-UI `/docs` → „Authorize“, künftige native Builds) bekommen den Token wie bisher im Body und setzen keinen Cookie. Der Body-Pfad dient ausserdem der **einmaligen Migration** alter `localStorage`-Tokens (Body-Token + Header → Antwort als Cookie).
- Keine Alembic-Migration nötig; `refresh_tokens` ist unverändert.

*CSRF-Schutz — Wahl: Pflicht-Header statt Double-Submit-Token*

- Für `/refresh` und `/logout` ist der Header `X-Requested-With: casa` **Pflicht, sobald der Token aus dem Cookie gelesen würde** (sonst 403 `CSRF_HEADER_MISSING`, der Token wird nicht angefasst). Wird der Token im Body mitgegeben, braucht es keinen Header — wer den Token kennt, ist kein CSRF-Angreifer.
- Begründung: Der Header ist nicht CORS-safelisted. HTML-Formulare können ihn nicht setzen, und `fetch`/XHR von einem fremden Origin löst einen Preflight aus, den nur die in `CORS_ORIGINS` konfigurierten Origins bestehen (Test `test_foreign_origin_preflight_with_csrf_header_rejected`). Ein Double-Submit-Token hätte entweder einen zweiten, für JS lesbaren Cookie oder eine Token-Auslieferung im Body gebraucht, also zusätzlichen Zustand ohne Sicherheitsgewinn gegenüber dem Header, denn beide Verfahren setzen voraus, dass der Angreifer keinen Code auf unserem Origin ausführt. Dazu kommen `SameSite=Strict` (Browser schickt den Cookie bei cross-site Requests gar nicht) und `Path=/api/auth` (Cookie geht nie an andere Endpunkte mit).
- Login und Register verlangen den Header **nicht**: Sie konsumieren keinen Cookie, und Swagger-UI postet das Login-Formular ohne eigene Header. Ein „Login-CSRF“ (Angreifer meldet das Opfer im eigenen Konto an) ist damit theoretisch möglich, scheitert aber am Preflight für die Cookie-Auslieferung (ohne Header kein Cookie) — akzeptiert.

*CORS (`backend/app/main.py`, Rückblick auf H-03)*

- `allow_credentials=True` ist wieder nötig, damit der Browser den Cookie im Cross-Origin-Dev-Setup (`VITE_API_URL`) annimmt und mitschickt. Erlaubt sind weiterhin nur die expliziten Origins aus `CORS_ORIGINS`; `X-Requested-With` steht in `allow_headers`. Ein `*` in `CORS_ORIGINS` würde Starlette mit Credentials jeden Origin spiegeln lassen und bricht deshalb den Start ab (`test_wildcard_cors_origin_prevents_startup`).
- In Produktion ist alles same-origin (nginx-Proxy), `SameSite=Strict` greift ohne Ausnahme. Empfehlung für die Entwicklung bleibt der Vite-Proxy (same-origin). `localhost:5173 → localhost:8000` ist ohnehin *same-site* (Ports zählen nicht), der Cookie funktioniert dort auch ohne Proxy.

*Frontend (`frontend/src/stores/auth.ts`, `api/client.ts`, `services/tokenStorage.ts`)*

- Der Access-Token lebt nur im Pinia-Store. Login, Register, Refresh und Logout nutzen `authRequestConfig()` (`withCredentials: true` + CSRF-Header). Der 401-Interceptor und der Socket.IO-Aufbau sind unverändert, sie arbeiten weiter mit dem Access-Token aus dem Store.
- `initialize()` holt den Access-Token beim Start per Cookie-Refresh. Ein **Sitzungs-Marker** `haushalt_session=1` in `localStorage` (kein Geheimnis) entscheidet, ob sich der Versuch lohnt, und ersetzt das frühere `storage`-Event auf `haushalt_tokens` für den **Cross-Tab-Sync**: Logout in einem Tab löscht den Marker, die anderen Tabs verwerfen ihren Access-Token und gehen zu `/login`; Login in einem Tab setzt den Marker, ausgeloggte Tabs übernehmen die Sitzung per Cookie-Refresh. Einen Abgleich des Refresh-Tokens zwischen Tabs braucht es nicht mehr, alle Tabs teilen sich den Cookie (das Grace-Window fängt gleichzeitige Refreshes ab).
- **Migration:** Ein vorhandener `haushalt_tokens`-Eintrag wird beim ersten Start gelesen, gelöscht und sein Refresh-Token einmalig per Body gegen den Cookie getauscht. Bestehende Sitzungen bleiben also erhalten; danach steht kein Token mehr in `localStorage`.
- **Offline-Start:** Schlägt der Start-Refresh mit einem Netzwerkfehler fehl, zeigt die App die Shell weiter („offline eingeloggt“, wie bisher), hat aber keinen Access-Token; der erste 401 nach Rückkehr des Netzes holt ihn nach.

*nginx (`frontend/nginx.conf`)*

- `proxy_pass` reicht `Set-Cookie` unverändert durch; es gibt kein `proxy_hide_header`, `proxy_cookie_path` oder `proxy_ignore_headers`. Der Pfad `/api/auth` bleibt erhalten. Dokumentiert als Kommentar in der Location `/api/`.

**Restrisiko / Bewertung:** XSS kann weiterhin den Access-Token (15 Min.) aus dem Speicher nehmen und, solange die Seite offen ist, selbst `/refresh` aufrufen — den Refresh-Token sieht es aber nie, die Session endet also mit dem Tab bzw. nach 15 Minuten statt nach 30 Tagen. Die strikte CSP (H-02) bleibt die erste Verteidigungslinie.

**Was ein nativer Build (Capacitor) später bräuchte:** Kein Browser-Cookie-Jar im selben Sinn, daher die vom Backend weiterhin unterstützte Body-Variante (Requests ohne `X-Requested-With: casa`) plus eine SecureStorage-Implementierung im Client, die den Refresh-Token hält und beim Start per Body-Refresh einlöst. Die Web-Variante bleibt davon unberührt.

**Vom Betreiber zu prüfen (Deployment hinter Nginx Proxy Manager):**

- `ENVIRONMENT=production` in `.env.prod` (setzt `Secure`). Nur ohne TLS testen mit `AUTH_COOKIE_SECURE=false`.
- NPM reicht `Set-Cookie` standardmässig durch; eine „Advanced“-Konfiguration darf `Set-Cookie` nicht filtern oder umschreiben (`proxy_cookie_path`/`proxy_cookie_domain`).
- HSTS in NPM aktivieren („HSTS enabled“), damit der `Secure`-Cookie nie über HTTP angefordert wird.
- Nach dem Deploy: Login im Browser → DevTools → Application → Cookies: `casa_rt` mit HttpOnly, Secure, SameSite=Strict, Path `/api/auth`; `localStorage` enthält kein `haushalt_tokens` mehr (nur `haushalt_session`, `haushalt_household_id` und UI-Präferenzen).

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

### H-03 — CORS (✅ Behoben, mit H-01 angepasst)

- Ursprünglich `allow_credentials=False`, weil Auth ausschliesslich über den `Authorization`-Header lief. **Seit H-01** ist `allow_credentials=True` wieder nötig (Refresh-Cookie mit `withCredentials`), aber nur für die explizit konfigurierten Origins; ein `*` in `CORS_ORIGINS` bricht den Start ab.
- `allow_methods` explizit (`GET, POST, PUT, PATCH, DELETE, OPTIONS`), `allow_headers` explizit (`Authorization, Content-Type, Accept, Accept-Language, X-Requested-With`).
- Produktion ist same-origin (nginx-Proxy), CORS greift nur im Dev-Setup. Socket.IO: Engine.IO-CORS ist deaktiviert und läuft über dieselbe Middleware — unverändert korrekt.
- Tests: erlaubter Origin (mit `Allow-Credentials: true`), CSRF-Header im Preflight erlaubt, fremder Origin (auch mit CSRF-Header) ohne `Allow-Origin`, unbekannter Header abgelehnt.

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

**H-12 (✅ Behoben):** Rotation durch Admins gibt es seit #11 (`POST /invite-code/rotate`); Einladungscodes laufen jetzt nach 7 Tagen ab (`households.invite_code_expires_at`, gesetzt beim Anlegen und bei jeder Rotation). Abgelaufene Codes werden bei Beitritt und Registrierung mit 410 `INVITE_CODE_EXPIRED` abgelehnt. Bestehende Haushalte erhalten bei der Migration 7 Tage ab Upgrade. Weiterhin offen (Produktfrage, bewusst nicht geändert): ob der Code nur für Admins sichtbar sein soll.

**H-14 (✅ Behoben):** `POST /files/` und `POST /documents/upload` (die einzigen Endpunkte, die Dateien entgegennehmen) tragen jetzt `@limiter.limit(UPLOAD_RATE_LIMIT)` mit `30/minute;300/hour` pro Client-IP (Konstante in `files.py`). Das reicht für mehrere Fotos/Seiten nacheinander, bremst aber Massen-Uploads; zusammen mit der Speicher-Quota pro Haushalt (`HOUSEHOLD_STORAGE_QUOTA_MB`) begrenzt es Rate und Volumen. Tierfotos laufen über `/files` (Pets referenzieren nur `photo_file_id`) und sind damit abgedeckt. Beide Routen zählen getrennt. Tests: `test_upload_rate_limit.py`.

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

`backend/tests/test_auth_cookie.py` (H-01, 26 Tests):
- Login/Register setzen `casa_rt` mit HttpOnly, SameSite=Strict, Path, Max-Age; `Secure` nur in production bzw. per `AUTH_COOKIE_SECURE`; Body ohne Refresh-Token; ohne Header weiterhin Body-Token und kein Cookie
- Refresh per Cookie rotiert und setzt den neuen Cookie; leerer Body; Cookie ohne CSRF-Header → 403 und Token unberührt; falscher Header-Wert → 403; kein Token → 401; ungültiger Cookie → 401 + Cookie gelöscht; Body-Refresh ohne Cookie; Migration Body-Token + Header → Cookie; Body hat Vorrang vor Cookie
- Grace-Window für zweiten Tab und Reuse-Detection (alle Sessions weg, Cookie gelöscht) über Cookies
- Logout per Cookie (revoked + löscht), ohne Body, ohne Header → 403, idempotent ohne Cookie, Body-Logout ohne Header
- Access-Token aus dem Cookie-Flow authentifiziert `/me`; `Cache-Control: no-store` auf allen Cookie-Responses

`backend/tests/test_startup_config.py`: Wildcard in `CORS_ORIGINS` erkannt und verhindert den Start.

`frontend/src/stores/__tests__/auth.test.ts` (22 Tests): Start ohne/mit Sitzungs-Marker, Migration alter `localStorage`-Tokens (auch unlesbar), Refresh 401 → ausgeloggt, Netzwerkfehler → offline eingeloggt, Single-Flight, Login/Register mit `withCredentials` + CSRF-Header, Logout (Backend-Call per Cookie, Fehlerfall, Single-Flight), Cross-Tab-Logout/-Login über den Marker.

`backend/tests/test_security_hardening.py` (27 Tests):
- Security-Header auf 200/401/429, keine API-CSP auf `/docs`, `no-store` auf Auth-Responses
- CORS: erlaubter/fremder Origin (auch mit CSRF-Header), unbekannter Header, Credentials nur für erlaubte Origins
- Rate-Limit registriert auf login/register/refresh/logout/join; Verhalten (429 + `RATE_LIMITED`) für join, refresh, logout
- JWT ohne `exp`, ohne `sub`, `alg=none` → 401
- Login mit unbekannter E-Mail führt Passwort-Vergleich aus
- Upload: GIF/BMP/TIFF als `image/png` → 422

---

## Gesamtbewertung

Die Auth-Architektur (kurzlebige JWTs, gehashte opake Refresh-Tokens, Rotation mit Reuse-Detection) ist solide und war bereits umgesetzt. Die grössten Lücken lagen in fehlenden HTTP-Security-Headern und einem ungeschützten Join-Endpoint — beides ist behoben. Mit H-01 liegt der langlebige Refresh-Token nun in einem HttpOnly-Cookie, XSS kommt nur noch an den 15-Minuten-Access-Token; die strikte CSP bleibt die erste Verteidigungslinie.

**Als Nächstes empfohlen (Reihenfolge):**
1. ✅ **Umgesetzt mit #14:** Pillow 12.3.0, PyJWT 2.15.0, urllib3 2.8.0, Werkzeug 3.1.9, multidict 6.9.1, cryptography 50.0.0 sowie `npm audit fix` (axios 1.20.0 u. a.). Offen: `dependency-audit` als Required Check einstellen.
2. ✅ **H-01** umgesetzt (HttpOnly-Refresh-Cookie, CSRF-Header, Migration in einem Release). Offen: Betreiber-Checks oben (HSTS, `ENVIRONMENT=production`).
3. ✅ **H-11** durch #8 behoben. Offen: HSTS in NPM aktivieren.
4. ✅ **H-12** behoben (Rotation + Ablauf). ✅ **H-14** behoben (Upload-Rate-Limit).
5. CSP-Monitoring: optional `report-to`-Endpoint, um Violations aus dem Feld zu sehen.
