# Casa — Production Deployment (Docker)

Production-Deployment auf einem Windows-Host mit Docker Desktop, hinter Nginx Proxy Manager (NPM) für TLS-Terminierung.

> ℹ️ Dieses Dokument beschreibt das **empfohlene Production-Deployment**. [DEPLOYMENT-WINDOWS-SERVER.md](./DEPLOYMENT-WINDOWS-SERVER.md) beschreibt einen einfachen HTTP-Testbetrieb mit der Entwicklungs-Konfiguration.

---

## 1. Erstes Deployment

### 1.1 Repository klonen

```powershell
cd C:\path\to
git clone <repo-url> haushalt-app
cd haushalt-app
```

### 1.2 Umgebungsdatei erstellen

```powershell
Copy-Item .env.prod.example .env.prod
```

Öffne `.env.prod` und passe **alle** Werte an:

### 1.3 NPM-Netzwerk ermitteln

Der Frontend-Container muss im selben Docker-Netzwerk wie Nginx Proxy Manager sein. Finde den Netzwerknamen:

```powershell
docker network ls
```

Typisches Ergebnis: `nginx-proxy-manager_default` oder `<npm-ordner>_default`. Trage den Namen in `.env.prod` ein:

```dotenv
NPM_NETWORK=nginx-proxy-manager_default
```

### 1.4 Secrets generieren

**JWT Secret Key** — mindestens 32 Zeichen, kryptographisch zufällig:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Ergebnis in `.env.prod` eintragen:

```dotenv
JWT_SECRET_KEY=<generierter-wert>
```

**Postgres-Passwort** — starkes, zufälliges Passwort setzen:

```dotenv
POSTGRES_PASSWORD=<starkes-passwort>
```

> ⚠️ Der Startup-Check lehnt den Placeholder-Wert aus `.env.prod.example` ab. Der Container startet nicht, solange `JWT_SECRET_KEY` nicht geändert wurde.

### 1.5 CORS-Origin anpassen

```dotenv
CORS_ORIGINS=https://deine-domain.example.com
```

### 1.6 Container starten

```powershell
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

### 1.7 Deployment prüfen

**Backend-Logs kontrollieren** — Alembic-Migrationen und Startup-Zeile müssen sichtbar sein:

```powershell
docker compose -f docker-compose.prod.yml logs backend
```

Erwartete Ausgabe (Auszug):

```
INFO  [alembic.runtime.migration] Running upgrade  -> a1205b17dbd0, ...
...
INFO:     Casa starting — env=production, db=postgres:5432/haushalt, cors=https://deine-domain.example.com, token_ttl=15min
```

**Keine exponierten Ports** — Postgres und Backend dürfen nicht von aussen erreichbar sein:

```powershell
docker ps
```

Die Spalte `PORTS` muss für `postgres` und `backend` **leer** sein. Nur `casa-frontend` ist im NPM-Netzwerk erreichbar (ebenfalls ohne Host-Port-Mapping).

---

## 2. NPM Proxy Host Settings

Erstelle in Nginx Proxy Manager einen neuen **Proxy Host** für die Casa-Domain:

### Details Tab

| Einstellung          | Wert              |
|----------------------|-------------------|
| Domain Names         | `casa.example.com`|
| Scheme               | `http`            |
| Forward Hostname     | `casa-frontend`   |
| Forward Port         | `80`              |
| Websockets Support   | ✅ ON             |
| Block Common Exploits| ✅ ON             |

### SSL Tab

| Einstellung          | Wert              |
|----------------------|-------------------|
| SSL Certificate      | Let's Encrypt     |
| Force SSL            | ✅ ON             |
| HTTP/2 Support       | ✅ ON             |

> ℹ️ `casa-frontend` ist der `container_name` aus `docker-compose.prod.yml`. NPM löst diesen Namen über das gemeinsame Docker-Netzwerk auf.

**Refresh-Token-Cookie:** Die Anmeldung setzt einen HttpOnly-Cookie `casa_rt` (`Secure`, `SameSite=Strict`, Path `/api/auth`). NPM reicht `Set-Cookie` standardmässig durch — in der „Advanced“-Konfiguration des Proxy Hosts nichts eintragen, das Cookies filtert oder umschreibt (`proxy_hide_header Set-Cookie`, `proxy_cookie_path`, `proxy_cookie_domain`). Weil der Cookie `Secure` ist, muss die App über HTTPS laufen (`ENVIRONMENT=production` in `.env.prod`); für einen reinen HTTP-Test `AUTH_COOKIE_SECURE=false` setzen. Empfohlen: im SSL-Tab zusätzlich **HSTS enabled**.

### Architektur-Überblick

```
Internet → NPM (TLS) → casa-frontend:80 (Nginx)
                          ├── /api/*       → backend:8000 ──┬── postgres:5432
                          ├── /socket.io/* → backend:8000   └── redis:6379 (Rate-Limits, Socket.IO-Queue)
                          └── /*           → Vue SPA (statisch)
```

---

## 3. Update-Prozedur

```powershell
cd C:\path\to\haushalt-app
git pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Alembic-Migrationen laufen **automatisch** beim Container-Start (`alembic upgrade head` im CMD des Backend-Dockerfile).

Für die [Audit-Korrekturen vom 7. Oktober 2026](qa/current-audit-fixes.md) Frontend und Backend aus demselben Stand gemeinsam neu bauen. Der Backend-Build installiert `pillow-heif==1.8.0` für die HEIC/HEIF-Konvertierung, falls der Browser das Foto nicht dekodieren kann. Dabei gelten weiterhin 10 MB pro Upload und 25 Megapixel vor dem serverseitigen Decode. Diese Korrekturen benötigen keine neue Datenbankmigration; ihre lokale Prüfung bestätigt kein Produktions-Deployment oder einen Test auf einem echten iPhone.

**Logs nach Update prüfen:**

```powershell
docker compose -f docker-compose.prod.yml logs --tail=50 backend
```

Kontrolliere, dass:
- Alembic-Migrationen fehlerfrei durchgelaufen sind
- Die Startup-Zeile `Casa starting — env=production, ...` erscheint
- Keine Tracebacks oder Fehler in den letzten Zeilen stehen

### 3.1 PWA-Clients nach einem Update

Die App ist als PWA installierbar (Service Worker cacht die App-Shell). Nach einem Frontend-Update
erhalten offene Clients einen Toast „Eine neue Version ist verfügbar — Neu laden“. Ohne Bestätigung
wird die neue Version aktiv, sobald alle Tabs/App-Fenster geschlossen wurden.

`/sw.js` und `/manifest.webmanifest` werden von nginx mit `Cache-Control: no-cache` ausgeliefert —
diese Header nicht im NPM überschreiben, sonst bleiben Clients auf alten Versionen hängen.

**Installation:** iOS Safari → Teilen → „Zum Home-Bildschirm“. Android Chrome → Menü → „App installieren“.
Voraussetzung ist HTTPS (bzw. `localhost`).

### 3.2 Push-Benachrichtigungen (Web Push) einrichten

Einmalig VAPID-Schlüssel erzeugen (im `backend/`-Ordner, oder im laufenden Container):

```powershell
docker compose -f docker-compose.prod.yml --env-file .env.prod exec backend python -m scripts.generate_vapid_keys
```

Die beiden Zeilen `VAPID_PUBLIC_KEY=…` / `VAPID_PRIVATE_KEY=…` in `.env.prod` eintragen, `VAPID_SUBJECT`
auf eine echte Kontaktadresse setzen (`mailto:…`) und das Backend neu starten. Im Log erscheint dann
`Push scheduler started`. Ohne Keys bleibt Push deaktiviert (`Push notifications disabled …`).

- **Keys nicht rotieren**, ausser bei Kompromittierung — neue Keys machen alle Geräte-Registrierungen
  ungültig; Nutzer müssen Benachrichtigungen dann neu aktivieren.
- Der Scheduler prüft jede Minute: fällige **Todo-Erinnerungen** (an die zugewiesene Person, sonst an
  alle Haushaltsmitglieder) und fällige **Tierpflege-Aufgaben** (ab 08:00 Haushalts-Zeitzone, an alle).
  Erinnerungen, die älter als 12 h sind (z.B. nach Server-Downtime), werden nicht nachgeschickt.
- Das Backend sendet ausgehend an die Push-Dienste von Google, Mozilla, Apple und Microsoft (HTTPS/443).
- Nutzer aktivieren Push pro Gerät unter **Einstellungen → App & Gerät → Benachrichtigungen**.
  Auf iPhone/iPad (ab iOS 16.4) nur, wenn die App zum Home-Bildschirm hinzugefügt wurde.

---

## 4. Rollback

### 4.1 Code-Rollback

Vorherigen Commit auschecken und Container neu bauen:

```powershell
git checkout <commit-hash>
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

### 4.2 Datenbank-Rollback

Falls das Update ein DB-Schema-Migration enthielt, die rückgängig gemacht werden muss, stelle einen Backup-Dump wieder her:

```powershell
.\scripts\restore-db.ps1 .\backups\casa-backup-YYYY-MM-DD_HH-mm.dump -ComposeFile docker-compose.prod.yml -EnvFile .env.prod
```

> ⚠️ `restore-db.ps1` überschreibt die gesamte Datenbank. Erstelle **immer** ein Backup vor einem Update (siehe Abschnitt 6).

---

## 5. JWT Secret Rotation

### 5.1 Neuen Secret generieren

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 5.2 In `.env.prod` ersetzen

```dotenv
JWT_SECRET_KEY=<neuer-wert>
```

### 5.3 Container neu starten

```powershell
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

> ⚠️ **Konsequenz:** Alle aktiven Access- und Refresh-Tokens werden sofort ungültig. Sämtliche eingeloggten User müssen sich neu anmelden.

---

## 6. Backups

### 6.1 Manuelles Backup

```powershell
.\scripts\backup-db.ps1 -ComposeFile docker-compose.prod.yml -EnvFile .env.prod
```

Erstellt mit gleichem Zeitstempel:

- `backups\casa-backup-YYYY-MM-DD_HH-mm.dump` — komprimierter PostgreSQL-Dump
- `backups\casa-uploads-YYYY-MM-DD_HH-mm.tar.gz` — alle hochgeladenen Dateien (Ablage-Dokumente, Tierfotos) aus dem Volume `uploaddata`

Postgres- und Backend-Container müssen laufen (die Uploads werden über den Backend-Container gelesen). Das Skript hält maximal 14 Backups je Typ und rotiert ältere automatisch.

### 6.2 Restore

```powershell
.\scripts\restore-db.ps1 .\backups\casa-backup-YYYY-MM-DD_HH-mm.dump -ComposeFile docker-compose.prod.yml -EnvFile .env.prod
```

Liegt neben dem Dump ein `casa-uploads-…tar.gz` mit gleichem Zeitstempel, werden auch die Uploads wiederhergestellt (bestehende Dateien werden ersetzt). Ein anderes Archiv lässt sich mit `-UploadsFile` angeben. Ohne Archiv bleiben die Dateien unverändert — Dokumente und Fotos aus dem Dump können dann auf fehlende Dateien zeigen.

### 6.3 Restore in Throwaway-Projekt (zum Testen)

Stellt den Dump in einem separaten Compose-Projekt wieder her, ohne die Produktionsdatenbank zu berühren:

```powershell
.\scripts\restore-db.ps1 .\backups\casa-backup-YYYY-MM-DD_HH-mm.dump -ComposeFile docker-compose.prod.yml -EnvFile .env.prod -ProjectName casa_test
```

Nach der Prüfung das Test-Projekt wieder aufräumen:

```powershell
docker compose -f docker-compose.prod.yml --env-file .env.prod --project-name casa_test down -v
```

### 6.4 Nightly Backup via Windows Task Scheduler

| Einstellung                              | Wert                                                                                       |
|------------------------------------------|---------------------------------------------------------------------------------------------|
| Programm                                 | `pwsh`                                                                                      |
| Argumente                                | `-File C:\path\to\haushalt-app\scripts\backup-db.ps1 -ComposeFile docker-compose.prod.yml -EnvFile .env.prod` |
| Starten in                               | `C:\path\to\haushalt-app`                                                                   |
| Run whether user is logged on or not     | ✅                                                                                          |
| Trigger                                  | Täglich, z.B. 03:00 Uhr                                                                    |

### 6.5 Offsite-Kopie

Empfehlung: Den `backups\`-Ordner regelmässig auf ein zweites Laufwerk oder in Cloud-Speicher (z.B. OneDrive, S3) kopieren.

---

## 7. Windows-spezifische Hinweise

Docker Desktop auf Windows startet Container erst, wenn Docker Desktop selbst läuft. Docker Desktop startet nur mit einer aktiven User-Session. Nach einem Windows-Update-Reboot kommen die Container **nur** zurück, wenn **alle drei** Bedingungen erfüllt sind:

### 7.1 Docker Desktop Autostart

Docker Desktop → Settings → General → **"Start Docker Desktop when you sign in"** ✅

### 7.2 Automatisches Anmelden

Der Server-Account muss sich nach einem Reboot automatisch anmelden, damit Docker Desktop starten kann:

```powershell
# Option A: netplwiz
netplwiz   # → "Users must enter a user name and password" deaktivieren
```

```powershell
# Option B: Registry
Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" -Name "AutoAdminLogon" -Value "1"
Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" -Name "DefaultUserName" -Value "<username>"
Set-ItemProperty -Path "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" -Name "DefaultPassword" -Value "<password>"
```

> ⚠️ Das Passwort wird im Klartext in der Registry gespeichert. Nur auf dedizierten Servern verwenden, nicht auf Geräten mit physischem Zugang durch Dritte.

### 7.3 Energieoptionen

Schlafmodus verhindert, dass Container dauerhaft laufen:

- Energiesparplan auf **"Höchstleistung"** setzen
- Schlafmodus und Ruhezustand **deaktivieren**

```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
```

### Warum das funktioniert

`restart: unless-stopped` in `docker-compose.prod.yml` sorgt dafür, dass alle Container **automatisch starten**, sobald Docker Desktop läuft. Die drei Bedingungen oben stellen sicher, dass Docker Desktop nach jedem Reboot zuverlässig startet.

---

## 8. Mehrere Backend-Prozesse (Redis)

`docker-compose.prod.yml` startet einen Redis-Container (ohne Persistenz) und setzt
`RATE_LIMIT_STORAGE_URI` und `SOCKETIO_MESSAGE_QUEUE` darauf. Damit teilen sich alle
Backend-Prozesse die Rate-Limit-Zähler und die Socket.IO-Räume, und Logout/Sperren
trennen die Verbindungen eines Users in jedem Prozess (Kontrollkanal `casa:socket-control`).

Mehr Worker einschalten (CPU-Kerne beachten, 2–4 reichen lange):

```
UVICORN_WORKERS=2
```

Ohne Redis (`SOCKETIO_MESSAGE_QUEUE` leer, `RATE_LIMIT_STORAGE_URI=memory://`) muss
`UVICORN_WORKERS=1` bleiben. Fällt Redis aus, zählt jeder Prozess die Rate-Limits
vorübergehend im Speicher weiter; Socket-Events erreichen dann nur noch Clients desselben Prozesses.

## 9. Fehler-Monitoring (Sentry)

Optional, ohne Personendaten (`send_default_pii=False`):

```
SENTRY_DSN=https://<key>@<org>.ingest.sentry.io/<project>
SENTRY_TRACES_SAMPLE_RATE=0
```

Der Startup-Log zeigt `sentry=on`. Zusätzlich zum Health-Check `/api/health` (DB-Prüfung)
empfiehlt sich ein externer Uptime-Monitor auf diese Adresse.

## 10. E-Mail, Tarife und Betreiber-Zugang

- **E-Mail** (Passwort vergessen, Bestätigung): `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
  `SMTP_PASSWORD`, `SMTP_TLS`, `MAIL_FROM`, `APP_BASE_URL` (öffentliche Adresse für Links).
  Ohne `SMTP_HOST` bleiben die Funktionen in Produktion ausgeblendet.
- **Tarife/Stripe** (nur SaaS-Betrieb): siehe [`monetization.md`](monetization.md).
- **Plattform-Admin** (Betreiber-Ansicht `/admin`, Tarife manuell setzen, Konten sperren):

```powershell
docker compose -f docker-compose.prod.yml --env-file .env.prod exec backend python -m scripts.make_platform_admin --email admin@example.com
```
