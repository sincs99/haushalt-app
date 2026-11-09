# Abnahme-Checkliste: ausgeführte Nachweise und Betreiberprüfungen

Stand: 2026-11-09. Diese Datei trennt strikt zwischen dem, was in einer Linux-Container-Umgebung
tatsächlich ausgeführt wurde (Teil 1), und dem, was nur der Betreiber auf echter Hardware und mit
echten Konten prüfen kann (Teil 2). Teil 2 ergänzt `docs/qa/REMEDIATION_STATUS.md` (Abschnitt 4)
und den Abschnitt "Deployment und verbleibende Betriebsnachweise" in
`docs/security/audit-remediation-2026-10-21.md`.

---

## Teil 1: Hier ausgeführt (2026-11-09)

Umgebung: Linux-Container, PostgreSQL 16 (eigener Wegwerf-Cluster auf Port 55433, `fsync=off`),
lokaler Redis, Python-venv mit den Backend-Abhängigkeiten. Der PostgreSQL-Cluster lief als
unprivilegierter Benutzer. Keine Produktionsdaten, keine echten Provider-Schlüssel.

| Schritt | Befehl (Kurzform) | Ergebnis |
|---|---|---|
| [x] Frische DB migrieren | `alembic upgrade head` (leere DB) | Kette bis `b4c5d6e7f8a9 (head)` ohne Fehler |
| [x] PostgreSQL-Testlane | `TEST_PG_URL=postgresql://…:55433/postgres pytest -m pg -q` | **71 bestanden**, 1277 abgewählt, 0 Fehler (42 s) |
| [x] Neun Sicherheits-Paralleltests | `TEST_AUTH_POSTGRES_URL` und `SECURITY_TEST_DATABASE_URL` auf separate DB `test_security`; `pytest -q tests/test_auth_concurrency_postgres.py tests/test_upload_ai_postgres.py` (wie CI-Job `backend-postgres`) | **9 bestanden**, 0 übersprungen |
| [x] Downgrade/Upgrade | `alembic downgrade -1 && alembic upgrade head` | `b4c5d6e7f8a9 -> b2c3d4e5f6a7 -> b4c5d6e7f8a9` fehlerfrei, `alembic current` = head |
| [x] Restore-Drill | `PG_ADMIN_URL=… PYTHON=python scripts/restore-drill.sh` | "Restore-Drill bestanden" (`y1z2a3b4c5d6 -> b4c5d6e7f8a9 -> Restore -> b4c5d6e7f8a9`); Tabellenvergleich identisch; Gegenprobe mit kaputtem Dump bricht ab, DB unverändert |
| [x] Restore-Orchestrierung (gemockte Befehle) | `python scripts/tests/test_restore_db_sh.py` | 9 Tests bestanden |
| [x] Compose-Syntax (Entwicklung) | `docker compose --env-file <Wegwerf-env> config -q` | gültig |
| [x] Mehrere Worker mit Redis | Redis auf Port 56379, `RATE_LIMIT_STORAGE_URI` und `SOCKETIO_MESSAGE_QUEUE` auf Redis, `uvicorn app.main:app --workers 2` gegen frisch migrierte DB | Beide Worker starten (Startzeile `rate_limit=redis, socket_queue=redis`); `/api/health` dreimal `200 {"status":"ok","db":true}`; Login-Limit `5/minute` greift workerübergreifend (5x 401, danach 429), Zähler liegt in Redis; Kanal `casa:socket-control` vorhanden |

Nicht ausführbar in dieser Umgebung:

| Schritt | Grund |
|---|---|
| [ ] Docker-Images bauen, Compose starten, Healthchecks | Der Docker-Daemon liess sich starten (Server 29.9.2, Image-Pull von Docker Hub funktionierte), aber der Backend-Build scheiterte bei `apt-get update`: der Agent-Proxy lehnt die Debian-Mirror-Anfragen ab (HTTP 405, Name nicht auflösbar). Umgebungsgrenze, kein Befund am Repository. Images, nginx-Konfiguration und Compose-Healthchecks sind damit weiterhin **nicht** geprüft (siehe Teil 2, Abschnitt A). Der Frontend-Build wurde nicht versucht. |
| [ ] Alles in Teil 2 | Echte Geräte, Windows-Server, NPM, Provider-Konten |

---

## Teil 2: Vom Betreiber auszuführen

Reihenfolge empfohlen: A, B, dann C bis I. Jeden Punkt abhaken und Datum notieren.

### A. Produktions-Deployment hinter Nginx Proxy Manager

Referenz: `docs/deployment.md` Abschnitte 1, 2, 2.1, 6a.

- [ ] **Compose-Auflösung prüfen.** `docker compose -f docker-compose.prod.yml --env-file .env.prod config -q`
  Erwartet: keine Meldung. Fehlt `POSTGRES_PASSWORD`, `JWT_SECRET_KEY` oder `NPM_TRUSTED_PROXY_IP`, bricht der Befehl mit einer Pflichtwert-Meldung ab (so ist es gewollt).
- [ ] **`NPM_TRUSTED_PROXY_IP` setzen.** `docker network inspect <NPM_NETWORK>`, IP des NPM-Containers eintragen. Im NPM-Stack statisch vergeben, damit ein Neustart sie nicht verschiebt. Kein CIDR, kein `*`.
- [ ] **Proxy-Subnetz ohne Überschneidung.** `docker network ls` und `docker network inspect` für alle vorhandenen Netze; `CASA_PROXY_SUBNET` (Standard `172.30.0.0/29`) und `CASA_FRONTEND_PROXY_IP` (Standard `172.30.0.3`) dürfen mit keinem anderen Netz kollidieren. Bei Kollision beide Werte gemeinsam ändern.
- [ ] **Starten.** `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build`
  Erwartet: Images bauen durch (inkl. `pillow-heif` im Backend), alle Container laufen.
- [ ] **Healthchecks.** `docker compose -f docker-compose.prod.yml ps`
  Erwartet: postgres, backend und frontend `healthy`.
- [ ] **Logs.** `docker compose -f docker-compose.prod.yml logs backend`
  Erwartet: Alembic-Läufe ohne Fehler (bei Update inkl. `b4c5d6e7f8a9`), Zeile `Casa starting — env=production, … rate_limit=redis, socket_queue=redis`, keine Tracebacks.
- [ ] **Keine offenen Ports.** `docker ps`
  Erwartet: Spalte PORTS leer für postgres und backend (Abschnitt 1.7).
- [ ] **NPM-Proxy-Host** nach Abschnitt 2: Scheme `http`, Forward `casa-frontend:80`, Websockets Support an, Block Common Exploits an, SSL Let's Encrypt, Force SSL, HTTP/2; empfohlen HSTS.
- [ ] **Health von aussen.** `curl -i https://<domain>/api/health`
  Erwartet: `200` und `{"status":"ok","db":true}`.
- [ ] **Login und Cookie.** Im Browser anmelden, in den Entwicklerwerkzeugen prüfen: Cookie `casa_rt` ist `HttpOnly`, `Secure`, `SameSite=Strict`, Path `/api/auth`. Nach Reload bleibt die Sitzung bestehen.
- [ ] **Echte Client-IP (Abschnitt 2.1).** In der von NPM erzeugten Konfiguration prüfen, dass `X-Forwarded-For` die echte Peer-Adresse enthält und `X-Forwarded-Proto` aus der TLS-Verbindung stammt. Praktischer Test: von zwei Netzen (WLAN und Mobilfunk) je 6 falsche Logins gegen die App. Erwartet: das Limit (5/Minute) gilt pro Client-IP, nicht gemeinsam; das Backend-Log zeigt die echten IPs, nicht die Proxy-IP.
- [ ] **Websocket.** Auf zwei Geräten im selben Haushalt eine Aufgabe abhaken. Erwartet: das zweite Gerät aktualisiert sich ohne Reload (Socket.IO über NPM).
- [ ] **Timeout für KI.** In NPM beim Proxy-Host unter "Custom Nginx Configuration" `proxy_read_timeout 200s;` eintragen (`docs/ai-assistant.md` Abschnitt 6). Das Frontend-nginx setzt dies bereits für `/api/households/*/ai/`; ohne NPM-Eintrag bricht der Browser nach dem NPM-Timeout ab, obwohl der Aufruf abgerechnet wird.
- [ ] **Cache-Header der PWA.** `curl -sI https://<domain>/sw.js` und `curl -sI https://<domain>/manifest.webmanifest`
  Erwartet: `Cache-Control: no-cache` (NPM darf das nicht überschreiben, Abschnitt 3.1).
- [ ] **Externer Uptime-Monitor** auf `https://<domain>/api/health` von einem anderen Gerät aus (Abschnitt 6a). Test: Backend kurz stoppen, Alarm muss kommen.
- [ ] **Mehrere Worker (optional).** `UVICORN_WORKERS=2` in `.env.prod`, `up -d`. Erwartet: Start ohne Fehler, Socket-Events erreichen Clients unabhängig vom Worker (Abschnitt 8).

### B. Backup und Restore mit den PowerShell-Skripten (Windows-Server)

Referenz: `docs/deployment.md` Abschnitte 4.2, 6.1 bis 6.5. `scripts/backup-db.ps1` und `scripts/restore-db.ps1` wurden bisher nie ausgeführt; getestet sind nur die Bash-Variante (`restore-db.sh`) und gemockte Abläufe.

- [ ] **Backup erzeugen.** `.\scripts\backup-db.ps1 -ComposeFile docker-compose.prod.yml -EnvFile .env.prod -Consistent`
  Erwartet: Exit-Code 0; im Ordner `backups\` ein `casa-backup-<Zeitstempel>.dump` und ein `casa-uploads-<Zeitstempel>.tar.gz` mit gleichem Zeitstempel, beide nicht leer; das Backend läuft danach wieder.
- [ ] **Fehlerfall.** Postgres-Container stoppen, Skript erneut starten. Erwartet: Exit-Code 1 mit Fehlermeldung (das Skript endet bei jedem Fehler mit 1).
- [ ] **Aufbewahrung und Off-Host.** `-Keep 14` und `-CopyTo \\nas\backup\casa` testen. Erwartet: Kopie am Ziel, Backups über der Aufbewahrungsgrenze werden entfernt.
- [ ] **Restore in Wegwerf-Umgebung** (nicht in Produktion; Abschnitt 6.3): separate Compose-Datei mit eigenen Containernamen, Volumes, Ports und Subnetz vorbereiten, Testdaten anlegen, Backup erzeugen, danach Daten ändern, dann `.\scripts\restore-db.ps1 .\backups\casa-backup-<Zeitstempel>.dump -ComposeFile docker-compose.test.yml -EnvFile .env.test -ProjectName casa_test`.
  Erwartet: Erfolgsmeldung, Stand entspricht dem Backup (spätere Änderungen sind weg), hochgeladene Dateien (Dokumente, Tierfotos) sind wieder abrufbar, Backend-Log zeigt sauberen Start. Danach `docker compose -f docker-compose.test.yml --env-file .env.test --project-name casa_test down -v`.
- [ ] **Kaputter Dump.** Kopie des Dumps abschneiden und restoren. Erwartet: Abbruch mit Fehler, die Datenbank bleibt unverändert.
- [ ] **Aufgabenplanung** nach Abschnitt 6.4 einrichten (`pwsh`, nachts, `-Consistent -CopyTo`). Nach dem ersten Lauf: "Letztes Ausführungsergebnis" = 0 und neue Dateien vorhanden.
- [ ] **Restore-Übung terminieren** (Abschnitt 6.5), z. B. quartalsweise, mit einem echten Backup.
- [ ] **Vor jedem Update mit Migration** ein Backup erzeugen. Rollback ist passender alter Code plus passender alter Dump, nicht `alembic downgrade` (Abschnitt 4).

### C. Web Push auf einem echten iPhone

Referenz: `docs/deployment.md` Abschnitt 3.2. Voraussetzung: iOS 16.4 oder neuer, HTTPS-Domain aus Teil A.

- [ ] **VAPID-Schlüssel erzeugen.** `docker compose -f docker-compose.prod.yml --env-file .env.prod exec backend python -m scripts.generate_vapid_keys`; `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` und `VAPID_SUBJECT=mailto:<echte Adresse>` in `.env.prod`, Backend neu starten.
  Erwartet: Log `Push scheduler started` (ohne Keys stattdessen `Push notifications disabled …`).
- [ ] **PWA installieren.** Safari, Teilen, "Zum Home-Bildschirm". App vom Home-Bildschirm starten (nicht im Safari-Tab).
- [ ] **Push aktivieren.** Einstellungen, App & Gerät, Benachrichtigungen aktivieren, iOS-Berechtigungsdialog bestätigen.
  Erwartet: Status aktiv; im Backend ist eine Zeile in `push_subscriptions` entstanden.
- [ ] **Zustellung.** Eine Todo-Erinnerung für die nächste Minute anlegen (der Scheduler läuft minütlich), App in den Hintergrund, Gerät sperren.
  Erwartet: Benachrichtigung erscheint nach spätestens etwa zwei Minuten; Tippen öffnet die App im richtigen Haushalt (`?hh=`, CASA-40); die Badge-Zahl stimmt.
- [ ] **Widerruf.** Benachrichtigungen in der App ausschalten, danach keine Zustellung mehr. Berechtigung in den iOS-Einstellungen entziehen; das Backend-Log darf keine Fehlerschleife zeigen.
- [ ] **Ausgehende Verbindung.** Bei ausbleibender Zustellung das Backend-Log nach Fehlern zu Apples Push-Dienst durchsuchen; ausgehend 443 muss vom Server erreichbar sein.

### D. Web Push auf Android

- [ ] **Chrome.** Menü, "App installieren", Benachrichtigungen aktivieren wie in C.
  Erwartet: Zustellung bei gesperrtem Gerät, Tippen öffnet den richtigen Haushalt.
- [ ] **Mehrere Haushalte.** Mit einem Konto in zwei Haushalten je eine Erinnerung auslösen. Erwartet: Tippen wechselt in den Haushalt der Meldung.

### E. PWA-Update-Ablauf auf iOS

Referenz: `docs/deployment.md` Abschnitt 3.1; `docs/qa/REMEDIATION_STATUS.md` (CASA-41, nicht auf installierter iOS-PWA getestet).

- [ ] **Ausgangsstand.** Installierte PWA öffnen, anmelden, vollständig beenden.
- [ ] **Neue Version ausliefern.** Frontend mit einer sichtbaren Änderung neu bauen und deployen (`up -d --build`).
- [ ] **Update-Hinweis.** PWA öffnen, einige Sekunden warten bzw. App kurz in den Hintergrund und zurück.
  Erwartet: Hinweis "Eine neue Version ist verfügbar." mit "Neu laden"; nach Tippen läuft die neue Version, die Sitzung bleibt erhalten.
- [ ] **Ohne Bestätigung.** Hinweis ignorieren, App aus dem App-Wechsler schliessen und neu starten. Erwartet: neue Version aktiv.
- [ ] **Offline.** Flugmodus an, App öffnen. Erwartet: App-Shell lädt aus dem Cache.

### F. HEIC-Foto vom iPhone hochladen

Referenz: `docs/qa/current-audit-fixes.md`, `docs/review-epic8-upload.md`. WebKit unter Windows ersetzt kein echtes iPhone.

- [ ] **Kamera-Upload.** iPhone-Kameraformat "High Efficiency" (HEIC). In einem Tierprofil oder bei einer Pflanze ein Foto aufnehmen und hochladen.
  Erwartet: Upload erfolgreich, Foto wird angezeigt und ist nach Reload weiterhin sichtbar, kein Fehler im Backend-Log.
- [ ] **Aus der Fotomediathek.** Ein vorhandenes HEIC-Foto wählen. Erwartet: wie oben.
- [ ] **Grenzen.** Eine Datei über 10 MB oder über 25 Megapixel hochladen. Erwartet: verständliche Fehlermeldung (`FILE_TOO_LARGE` bzw. Pixelgrenze), kein Absturz.
- [ ] **Ablage-Dokument.** Dasselbe als Dokument in der Ablage. Erwartet: Datei lässt sich öffnen.

### G. NFC/QR-Tag-Scan

Referenz: `docs/PROJECT-STATUS.md` Epic 32, `docs/security/tags-review.md`.

- [ ] **Tag anlegen.** Unter Haushalt, Tags, einen Tag mit Ziel und Aktion erstellen (z. B. Haustier füttern). Erwartet: QR-Code mit Inhalt `https://<domain>/t/<token>`.
- [ ] **QR-Scan.** Mit der iPhone-Kamera scannen. Erwartet: Link öffnet sich; ohne Anmeldung erst Login, dann Rücksprung auf `/t/<token>`; die Aktion läuft erst nach Tippen auf der Bestätigungsseite.
- [ ] **NFC schreiben (nur Android/Chrome, Web NFC).** Leeren NFC-Chip beschreiben. Erwartet: Erfolgsmeldung. Auf iOS ist Schreiben nicht möglich.
- [ ] **NFC lesen.** Chip an iPhone und Android halten. Erwartet: öffnet `https://<domain>/t/<token>`, dieselbe Bestätigungsseite.
- [ ] **Wirkung.** Nach der Aktion den Zustand prüfen (z. B. Fütterung eingetragen) und auf einem zweiten Gerät die Live-Aktualisierung beobachten. Tag deaktivieren und erneut scannen: Erwartet Ablehnung.
- [ ] **Logs.** `docker compose -f docker-compose.prod.yml logs frontend`. Erwartet: Tokens im Pfad des nginx-Access-Logs sind geschwärzt.

### H. Ein echter Aufruf des KI-Assistenten

Referenz: `docs/ai-assistant.md` Abschnitte 4, 5, 6. Bisher gab es keinen echten API-Aufruf; die Token-Zahlen im Dokument sind Schätzungen.

- [ ] **Ausgabenlimit beim Anbieter** in der Anthropic-Console setzen (Aufrufzahlen sind keine feste Geldobergrenze); `AI_DAILY_LIMIT_GLOBAL` passend wählen.
- [ ] **Schlüssel eintragen.** `ANTHROPIC_API_KEY=<echter Schlüssel>` in `.env.prod`, `up -d`.
- [ ] **Status.** In der App prüfen, ob KI-Elemente erscheinen (`GET /api/ai/status` liefert `enabled: true`).
- [ ] **Opt-in.** Als Haushalts-Admin den Assistenten für den Haushalt einschalten. Vor dem Opt-in: Aufruf liefert 403 `AI_NOT_ENABLED`.
- [ ] **Rezept.** Ein Rezept per KI erzeugen.
  Erwartet: Vorschlag kommt zurück (kann über 60 Sekunden dauern), wird nicht automatisch gespeichert; kein Abbruch durch NPM (Timeout aus Teil A). Backend-Log: `AI call ok model=… input_tokens=… output_tokens=…`.
- [ ] **Pflanzenpflege.** Bei einer Pflanze Pflegehinweise per KI abrufen. Erwartet: Intervalle, Licht, Giftigkeit.
- [ ] **Verbrauch prüfen.** Die SQL-Abfrage aus `docs/ai-assistant.md` Abschnitt 4 (`ai_usage`) ausführen und die echten Token-Zahlen mit den Schätzungen vergleichen; Dokument anpassen.
- [ ] **Limits.** `AI_DAILY_LIMIT_PER_USER=1` setzen, zwei Aufrufe machen. Erwartet: der zweite wird mit `AI_USER_DAILY_LIMIT_REACHED` abgewiesen. Wert danach zurücksetzen.
- [ ] **Fehlerfall.** Mit ungültigem Schlüssel einen Aufruf versuchen. Erwartet: 502 `AI_UNAVAILABLE`, keine Schlüsseldetails in der Antwort.

### I. Stripe-Checkout im Testmodus (nur bei Abrechnung)

Referenz: `docs/monetization.md` Abschnitt 2. Nur mit `sk_test_…`-Schlüsseln, nie mit Live-Schlüsseln testen.

- [ ] **Konfiguration.** `.env.prod`: `BILLING_ENABLED=true`, `STRIPE_SECRET_KEY=sk_test_…`, `STRIPE_WEBHOOK_SECRET=whsec_…`, `STRIPE_PRICE_ID_MONTHLY`, `STRIPE_PRICE_ID_YEARLY`, `APP_BASE_URL=https://<domain>`, `LEGAL_TERMS_REQUIRED=true`. Backend neu starten.
- [ ] **Webhook anlegen.** Stripe-Testmodus, Endpoint `https://<domain>/api/billing/webhooks/stripe` mit `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`. Kundenportal aktivieren.
- [ ] **Checkout.** Als Admin eines Haushalts mit bestätigter E-Mail "Auf Premium wechseln", mit Testkarte `4242 4242 4242 4242` bezahlen.
  Erwartet: Rückkehr auf `/household?billing=success`, Tarif wechselt per Webhook auf `premium` (kann wenige Sekunden dauern).
- [ ] **Idempotenz.** Das Event im Stripe-Dashboard erneut zustellen. Erwartet: kein doppelter Effekt (`billing_events`).
- [ ] **Signatur.** Mit falschem `STRIPE_WEBHOOK_SECRET` zustellen. Erwartet: Ablehnung, Tarif unverändert.
- [ ] **Kündigung.** Über das Kundenportal kündigen. Erwartet: Tarif fällt auf `free` zurück.
- [ ] **Vor Live-Betrieb** Steuern klären (Stripe Tax oder Merchant of Record, `docs/monetization.md`).

### J. Abschluss

- [ ] Ergebnisse (Datum, Gerät, iOS-/Android-Version, Auffälligkeiten) festhalten und erledigte Punkte in `docs/qa/REMEDIATION_STATUS.md` Abschnitt 4 nachführen.
- [ ] Offene Hinweise aus `docs/security/audit-remediation-2026-10-21.md` abhaken: NPM-Header-Bereinigung, Netzbelegung, Provider-Hartlimits, Produktivmigration, neue Scriptable-Vorlage auf bestehenden Geräten übernehmen (`docs/widget.md`).
