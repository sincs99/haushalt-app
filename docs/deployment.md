# Casa — Production Deployment (Docker)

Production-Deployment auf einem Windows-Host mit Docker Desktop, hinter Nginx Proxy Manager (NPM) für TLS-Terminierung.

> ℹ️ Dieses Dokument beschreibt das **Docker-basierte Production-Deployment**. Für ein alternatives Setup ohne Docker siehe [DEPLOYMENT-WINDOWS-SERVER.md](./DEPLOYMENT-WINDOWS-SERVER.md).

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

### Architektur-Überblick

```
Internet → NPM (TLS) → casa-frontend:80 (Nginx)
                          ├── /api/*       → backend:8000
                          ├── /socket.io/* → backend:8000 (WebSocket)
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

**Logs nach Update prüfen:**

```powershell
docker compose -f docker-compose.prod.yml logs --tail=50 backend
```

Kontrolliere, dass:
- Alembic-Migrationen fehlerfrei durchgelaufen sind
- Die Startup-Zeile `Casa starting — env=production, ...` erscheint
- Keine Tracebacks oder Fehler in den letzten Zeilen stehen

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

Erstellt einen komprimierten PostgreSQL-Dump unter `backups\casa-backup-YYYY-MM-DD_HH-mm.dump`. Das Skript hält maximal 14 Backups und rotiert ältere automatisch.

### 6.2 Restore

```powershell
.\scripts\restore-db.ps1 .\backups\casa-backup-YYYY-MM-DD_HH-mm.dump -ComposeFile docker-compose.prod.yml -EnvFile .env.prod
```

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

> ℹ️ **Hinweis zu File Uploads:** Sobald Epic 9 (File Uploads) produktiv genutzt wird, muss auch das Docker-Volume `uploaddata` in die Backup-Strategie einbezogen werden. Der Volume-Pfad lässt sich mit `docker volume inspect <project>_uploaddata` ermitteln.

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
