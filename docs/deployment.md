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

Setze zusätzlich `NPM_TRUSTED_PROXY_IP` auf die **exakte IP des NPM-Containers in diesem Netzwerk**. Vergib sie im NPM-Stack statisch, damit ein Container-Neustart die Vertrauensgrenze nicht verschiebt. Die Adresse wird in der Nginx-Konfiguration ausschließlich für diesen Peer verwendet. Ein gesamtes privates oder Docker-Netz ist kein geeigneter Ersatz.

```powershell
docker network inspect nginx-proxy-manager_default
```

Das Frontend erreicht die API über ein separates internes Netz; nur seine feste Adresse wird vom Backend als Proxy akzeptiert. Standard: `CASA_PROXY_SUBNET=172.30.0.0/29`, `CASA_FRONTEND_PROXY_IP=172.30.0.3`. Bei einer Überschneidung mit vorhandenen Netzen beide Werte zusammen anpassen. Das Frontend ist nicht mehr im Datenbanknetz. Die API selbst behält ausgehenden Zugriff über ihr Datenbank-/Default-Netz für Push und KI.

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

**Refresh-Token-Cookie:** Die Anmeldung setzt einen HttpOnly-Cookie `casa_rt` (`Secure`, `SameSite=Strict`, Path `/api/auth`). NPM muss `Set-Cookie` unverändert durchreichen; keine Cookie-Umschreibung oder Filterung konfigurieren. Production Compose erzwingt `ENVIRONMENT=production` und `AUTH_COOKIE_SECURE=true`, und der Backend-Start lehnt eine unsichere Produktionskonfiguration ab. Reine HTTP-Tests gehören in die Entwicklungs-Konfiguration. Empfohlen: im SSL-Tab zusätzlich **HSTS enabled**.

**Proxy-Nachweis beim Betreiber:** In der tatsächlich erzeugten NPM-Konfiguration prüfen, dass `X-Forwarded-For` durch die echte Peer-Adresse ersetzt oder um diese ergänzt wird und `X-Forwarded-Proto` aus der TLS-Verbindung stammt. In `docker network inspect` dürfen keine unkontrollierten Workloads die konfigurierte vertrauenswürdige NPM-Adresse belegen. Das Frontend reicht eine einzelne bereinigte Client-IP weiter und akzeptiert nur `http`/`https` vom konfigurierten Proxy-Peer. Diese Repository-Konfiguration ersetzt keine Prüfung der vorhandenen Installation.

### 2.1 Echte Client-IP: vertrauenswürdige Proxies

Rate-Limits (Login, KI, …) und Logs brauchen die echte Client-IP. Sie kommt über zwei Stufen:

| Stufe | Wer vertraut wem | Variable (`.env.prod`) | Default |
|---|---|---|---|
| Frontend-nginx | übernimmt `X-Forwarded-For` nur von NPM | `NPM_TRUSTED_PROXY_IP` | Pflichtwert: feste NPM-IP |
| Backend (uvicorn) | übernimmt den Header nur vom Frontend-nginx | `CASA_FRONTEND_PROXY_IP` setzt `FORWARDED_ALLOW_IPS` | `172.30.0.3` |

Die tatsächliche NPM-Adresse und das separate Frontend-/Backend-Netz prüfen:

```powershell
docker network inspect <NPM_NETWORK>
docker network inspect haushalt-app_app_proxy
```

Bei einer Subnetz-Kollision `CASA_PROXY_SUBNET` und `CASA_FRONTEND_PROXY_IP` gemeinsam ändern.
Symptom bei falscher NPM-Adresse: Nutzer teilen sich ein Rate-Limit, Logs zeigen nur die Proxy-IP.
Keine pauschalen CIDRs oder `*` einsetzen. Die Nginx-Vorlage übernimmt ausschließlich
`NPM_TRUSTED_PROXY_IP`; der bisherige `TRUSTED_PROXY_CIDRS`-Start-Hook wird nicht mehr eingebaut.

### Architektur-Überblick

```
Internet → NPM (TLS) → casa-frontend:80 (Nginx)
                          ├── /api/*       → backend:8000 ──┬── postgres:5432
                          ├── /socket.io/* → backend:8000   └── redis:6379 (Rate-Limits, Socket.IO-Queue)
                          └── /*           → Vue SPA (statisch)
```

---

## 3. Update-Prozedur

Für die [UI-/Geschäftslogik-Korrekturen vom 22. Oktober 2026](qa/ui-business-fixes-20261022.md) Frontend und Backend gemeinsam aktualisieren. Diese Änderungen benötigen keine zusätzliche Migration; bestehende Windows-Dateischlüssel werden ohne Datenumschreibung erkannt. Der gemeinsame Release-Zweig enthält weiterhin die Sicherheitsmigration `b4c5d6e7f8a9` für KI-Budgets. Bei einem Update von einem älteren Stand gelten deshalb die Backup- und Migrationshinweise für diese Sicherheitskorrekturen. Nach dem Update Ausgabenbearbeitung mit Versionskonflikt, Verlauf/Nachladen, bestehende Uploads und das Haushaltsdatum prüfen; die lokale Chromium-Abnahme ersetzt diese Betriebsprüfung nicht.

Für die Sicherheitskorrekturen vom 21. Oktober 2026 Frontend und Backend gemeinsam aktualisieren. Vorher `NPM_TRUSTED_PROXY_IP` setzen und das neue interne Proxy-Netz auf Überschneidungen prüfen. Die KI-Budgets benötigen die neue Alembic-Migration; sie läuft beim Backend-Start. Beim ersten Deployment der schlüsselgebundenen Refresh-Hashes werden vorhandene Refresh-Sitzungen einmalig ungültig und Nutzer melden sich erneut an. Es gibt keinen Rückfall auf die früheren ungebundenen SHA-256-Hashes. Für bereits installierte Scriptable-Widgets die neue Skriptvorlage übernehmen.

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

## 4. Rollback und Wiederherstellung

**Migrationen sind forward-only** (PD-D2). Ein Update mit Migration wird nicht per
`alembic downgrade` und auch nicht per „alten Dump über die neue DB spielen“ zurückgenommen.
Fehler nach einem Update werden mit einem weiteren Update behoben (Fix-Forward). Ein Restore
ist **Disaster-Recovery** (Datenverlust, kaputte DB, missglücktes Update ohne Fix).

### 4.1 Code-Rollback (nur ohne Migration)

Enthielt das Update **keine** Migration (`backend/migrations/versions/` unverändert zwischen
den beiden Ständen), genügt der alte Code:

```powershell
git checkout <commit-hash>
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Mit Migration startet alter Code gegen die neuere DB nicht (Alembic kennt die Revision nicht) —
dann 4.2.

### 4.2 Wiederherstellung = passender alter Code + passender alter Dump

Ein Dump gehört zu dem Code-Stand, mit dem er erstellt wurde. Rollback bedeutet deshalb immer
**beides** zurück:

1. Code auf den Stand des Backups bringen (`git checkout <commit>` — der Commit, der beim Backup
   lief; das Backup vor jedem Update anlegen, siehe Abschnitt 6) und Images bauen:
   `docker compose -f docker-compose.prod.yml --env-file .env.prod build`
2. Dump (und Uploads) wiederherstellen:

```powershell
.\scripts\restore-db.ps1 .\backups\casa-backup-YYYY-MM-DD_HH-mm.dump -ComposeFile docker-compose.prod.yml -EnvFile .env.prod
```

Das Skript (CASA-07):

- validiert das Upload-Archiv und bereitet seine Dateien separat vor,
- stoppt das Backend (keine Schreibzugriffe während des Restores),
- spielt den Dump in eine **frische** Datenbank mit eindeutigem Restore-Namen ein —
  `pg_restore --single-transaction --exit-on-error`: jeder Fehler bricht ab, die Produktions-DB
  bleibt dann unverändert,
- tauscht erst danach: `haushalt` → `haushalt_before_restore_<Zeitstempel>`, Restore-Datenbank → `haushalt`,
- stellt das Uploads-Archiv mit gleichem Zeitstempel wieder her (Hilfscontainer mit dem Upload-Volume),
- startet ein zuvor laufendes Backend (`alembic upgrade head`) und wartet auf `/api/health`.

Jeder Fehler beendet das Skript mit Exit-Code 1. Vor dem DB-Tausch kann das zuvor laufende Backend mit der ursprünglichen DB wieder starten. Nach dem Tausch bleibt es bei Fehlern angehalten. Die vorherige
Datenbank bleibt als `haushalt_before_restore_<Zeitstempel>` liegen (Rückweg, falls der falsche
Dump erwischt wurde); nach der Prüfung löschen (der Befehl steht in der Ausgabe) oder gleich
`-DropOld` angeben (Löschung erst nach erfolgreichem Abschluss). Ohne Rückfrage (Automatisierung): `-Yes`.

Ist der Code **neuer** als der Dump, migriert das Backend den wiederhergestellten Stand beim
Start nach vorne — das ist der normale Weg nach Datenverlust (Dump von gestern + heutiger Code).

> ⚠️ Der frühere Ablauf (`pg_restore --clean --if-exists` über die laufende DB) hinterliess bei
> einem Dump von vor einem Update eine gemischte Datenbank und einen Backend-Neustart-Loop
> (`DuplicateTable`). Nicht mehr so wiederherstellen.

**Restore-Drill:** `scripts/restore-drill.sh` spielt den Ablauf gegen eine Wegwerf-DB durch
(alte Revision → Backup → Update + neue Daten → Restore → exakter Vergleich aller Tabellen →
`alembic upgrade head`; Gegenprobe mit kaputtem Dump). Läuft in CI im Job `backend-postgres`.
Lokal: `PG_ADMIN_URL=postgresql://user:pw@localhost:5432/postgres scripts/restore-drill.sh`.
Auf Linux-Hosts gibt es `scripts/restore-db.sh` mit derselben Logik wie `restore-db.ps1`.

Das Restore-Skript benötigt das aktuelle Backend-Image mit `scripts/restore_uploads.py`. Es prüft das Upload-Archiv vor jeder Änderung an SQL oder vorhandenen Uploads und entpackt es zunächst in einen separaten Bereich des Upload-Volumes. Erlaubt sind nur reguläre Dateien und Verzeichnisse unter `uploads/`; Links, Geräte, Traversal-Pfade und doppelte Einträge werden abgelehnt. Standardgrenzen: 100.000 Einträge und 20 GiB entpackte Daten; zusätzlich muss genügend freier Speicher für die neue Kopie vorhanden sein. Größere Archive erst mit bewusst angepassten Grenzen vorbereiten.

Vor dem SQL-Restore wird das Backend angehalten. `pg_restore` läuft mit `--single-transaction --exit-on-error`; bei Fehlern vor dem DB-Tausch werden Uploads nicht ersetzt und ein zuvor laufender Dienst kann mit der ursprünglichen DB wieder starten. Erst nach erfolgreicher Datenbank- und Upload-Wiederherstellung wird ein vorher laufendes Backend gestartet. Ein Fehler beim Upload-Tausch erhält den vorbereiteten Bereich mit der ausgegebenen Staging-ID; die Datenbank kann dann bereits den neuen Stand haben. In diesem Zustand den Dienst nicht starten, bis Dateibestand und Datenbank wieder zusammenpassen. Eine Wiederaufnahme verwendet ausschließlich diese geprüfte Staging-ID. Das ersetzt keine gemeinsame Transaktion über SQL und Dateisystem.

Nach einem fehlgeschlagenen Upload-Tausch und bereits erfolgreichem SQL-Restore den **Helper** mit der ausgegebenen Staging-ID wiederaufnehmen, nicht das gesamte PowerShell-Skript (damit Datenbank und Uploads nicht erneut vorbereitet und getauscht werden):

```powershell
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm --no-deps --entrypoint python backend /app/scripts/restore_uploads.py apply <staging-id>
# Erst nach erfolgreichem Helper und geprüftem gemeinsamen Stand:
docker compose -f docker-compose.prod.yml --env-file .env.prod start backend
```

Ist schon der SQL-Restore fehlgeschlagen, wurde dessen Transaktion zurückgerollt: vorhandene Uploads nicht durch den Helper ersetzen. Den Fehler beheben und den Datenbank-/Dateistand prüfen. Nichtleere Rückstände in `previous/` bedeuten einen unvollständigen Dateitausch und müssen vor einer Wiederaufnahme gezielt abgeglichen werden. Parallele Compose-Projekte benötigen unterschiedliche interne Proxy-Subnetze; für Test-Restores eigene Werte setzen.

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

Postgres- und Backend-Container müssen laufen (die Uploads werden über den Backend-Container gelesen).

| Option | Wirkung |
|---|---|
| `-Consistent` | Stoppt das Backend während des Backups (meist < 1 Minute) — Dump und Uploads sind dann exakt ein Paar. Empfohlen für das nächtliche Backup. |
| `-Keep 14` | Anzahl aufbewahrter Backups je Typ (Default 14 = zwei Wochen bei täglichem Lauf) |
| `-CopyTo <Pfad>` | Kopiert das Paar zusätzlich an einen zweiten Ort (gleiche Aufbewahrung dort) |

**Konsistenz ohne `-Consistent`:** Das Skript sichert zuerst die Datenbank (Snapshot), danach die
Uploads. Jede Datei, auf die der Dump zeigt, ist damit im Archiv — ausser sie wurde genau zwischen
den beiden Schritten gelöscht. Zusätzliche, neuere Dateien im Archiv sind harmlos (verwaiste
Uploads räumt das Backend auf). Für ein garantiert passendes Paar `-Consistent` verwenden.

### 6.2 Restore

```powershell
.\scripts\restore-db.ps1 .\backups\casa-backup-YYYY-MM-DD_HH-mm.dump -ComposeFile docker-compose.prod.yml -EnvFile .env.prod
```

Ablauf und Voraussetzungen (passender Code-Stand!) siehe Abschnitt 4.2. Liegt neben dem Dump ein `casa-uploads-…tar.gz` mit gleichem Zeitstempel, werden auch die Uploads wiederhergestellt (bestehende Dateien werden ersetzt). Ein anderes Archiv lässt sich mit `-UploadsFile` angeben, `-NoUploads` lässt die Dateien unverändert — Dokumente und Fotos aus dem Dump können dann auf fehlende Dateien zeigen.

### 6.3 Restore in Throwaway-Projekt (zum Testen)

`-ProjectName` allein isoliert die Produktionskonfiguration nicht ausreichend: `docker-compose.prod.yml` enthält feste Containernamen und ein festes Proxy-Subnetz. Für einen parallelen Restore-Test zuerst eine separate Compose-Datei und Test-Umgebung vorbereiten: eigene Containernamen (oder projektbezogene Standardnamen), eigene Volumes, kollisionsfreie Ports/Subnetze und keine Verbindung zum produktiven NPM-Netz. Keine Produktions-Zugangsdaten oder echten Provider-Schlüssel übernehmen.

Die folgenden Befehle setzen diese separat vorbereiteten Dateien und bereits gestarteten Test-Container voraus:

```powershell
.\scripts\restore-db.ps1 .\backups\casa-backup-YYYY-MM-DD_HH-mm.dump -ComposeFile docker-compose.test.yml -EnvFile .env.test -ProjectName casa_test
```

Nach der Prüfung das Test-Projekt wieder aufräumen:

```powershell
docker compose -f docker-compose.test.yml --env-file .env.test --project-name casa_test down -v
```

### 6.4 Nightly Backup via Windows Task Scheduler

| Einstellung                              | Wert                                                                                       |
|------------------------------------------|---------------------------------------------------------------------------------------------|
| Programm                                 | `pwsh`                                                                                      |
| Argumente                                | `-File C:\path\to\haushalt-app\scripts\backup-db.ps1 -ComposeFile docker-compose.prod.yml -EnvFile .env.prod -Consistent -CopyTo \\nas\backup\casa` |
| Starten in                               | `C:\path\to\haushalt-app`                                                                   |
| Run whether user is logged on or not     | ✅                                                                                          |
| Trigger                                  | Täglich, z.B. 03:00 Uhr                                                                    |

Der Task muss fehlschlagen dürfen: Das Skript endet bei jedem Fehler mit Exit-Code 1 — in der
Aufgabenplanung „Verlauf“ aktivieren bzw. den letzten Laufergebnis-Code überwachen.

### 6.5 Off-Host-Kopie und Aufbewahrung

Ein Backup auf demselben Host schützt nicht vor Plattenausfall, Verschlüsselungstrojaner oder
Diebstahl. Mindestens eine Kopie gehört auf ein anderes Gerät:

- `-CopyTo` auf ein zweites Laufwerk, eine NAS-Freigabe (`\\nas\backup\casa`) oder einen
  synchronisierten Cloud-Ordner (OneDrive/Dropbox). Der Task-Benutzer braucht Schreibrechte.
- Besser zusätzlich versioniert und verschlüsselt, z. B. mit `restic` oder `rclone` in einem zweiten
  Task nach dem Backup (S3, Backblaze B2, …) — dann überlebt auch ein versehentlich überschriebenes
  Backup.
- Aufbewahrung: täglich 14 (`-Keep`), am Off-Host-Ziel gern länger (z. B. 4 Wochen-/12 Monats-Stände
  per restic `forget --keep-daily 14 --keep-weekly 8 --keep-monthly 12`).
- Dumps und Uploads enthalten personenbezogene Daten (Ausgaben, Dokumente, Fotos): Ziel nur für den
  Betreiber zugänglich, Cloud-Ziele verschlüsselt.
- **Restore regelmässig üben** (z. B. quartalsweise): Abschnitt 6.3 mit einem echten Backup. CI prüft
  den Ablauf zusätzlich mit `scripts/restore-drill.sh`.

---

## 6a. Monitoring, Alarmierung und Logs

### Alarmierung über `/api/health`

`GET /api/health` (ohne Login) prüft Backend **und** Datenbank: `200 {"status":"ok","db":true}`,
bei DB-Problemen `503 {"status":"error","db":false}`. Von **ausserhalb** des Servers überwachen —
ein Healthcheck im selben Docker merkt einen Host-Ausfall nicht:

- Uptime Kuma (selbst gehostet, auf einem anderen Gerät), UptimeRobot, Better Stack o. ä.
- Ziel: `https://<domain>/api/health`, Intervall 1–5 Minuten, Alarm bei Status ≠ 200 oder fehlendem
  `"status":"ok"` nach 2–3 Fehlversuchen; Benachrichtigung per E-Mail/Push.
- Zusätzlich das TLS-Zertifikat (Ablauf) überwachen, falls das Tool es anbietet.

Docker-Healthchecks (`docker compose ps` → `healthy`): Backend prüft `/api/health`, Frontend prüft
`/nginx-health` (nur nginx), Postgres `pg_isready`. Sie starten Container nicht automatisch neu,
zeigen aber den Zustand und steuern die Startreihenfolge.

### Log-Rotation

Alle Container schreiben über den `json-file`-Treiber mit Rotation (`x-logging` in den Compose-
Dateien): Default 5 Dateien à 10 MB pro Container, anpassbar mit `LOG_MAX_SIZE`/`LOG_MAX_FILE` in
`.env.prod`. Die Einstellung gilt erst für neu erstellte Container (`up -d` nach der Änderung).
Fehlersuche: `docker compose -f docker-compose.prod.yml logs --since 1h backend`.

Ein Error-Tracking-Dienst (z. B. Sentry) ist nicht eingebaut; Fehler erscheinen als Traceback im
Backend-Log.

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
