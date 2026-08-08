# Deployment-Anleitung: Haushalt-App auf Windows Server

> **Ziel:** Die Haushalt-App mit Docker Compose auf einem Windows Server produktiv betreiben.
>
> **Stand:** August 2026 · **Getestet mit:** Windows Server 2022, Docker Desktop 4.x

---

## Inhaltsverzeichnis

1. [Voraussetzungen](#voraussetzungen)
2. [Docker installieren](#schritt-1-docker-installieren)
3. [Repository klonen](#schritt-2-repository-klonen)
4. [Umgebungsvariablen konfigurieren](#schritt-3-umgebungsvariablen-konfigurieren)
5. [App bauen und starten](#schritt-4-app-bauen-und-starten)
6. [Prüfen ob alles läuft](#schritt-5-prüfen-ob-alles-läuft)
7. [Windows Firewall konfigurieren](#schritt-6-windows-firewall-konfigurieren)
8. [Nützliche Befehle](#nützliche-befehle)
9. [Update-Workflow](#update-workflow)
10. [Optional: HTTPS mit Caddy](#optional-https-mit-caddy)
11. [Troubleshooting](#troubleshooting)

---

## Voraussetzungen

| Anforderung | Details |
|---|---|
| **Betriebssystem** | Windows Server 2022 oder neuer |
| **Zugang** | RDP-Zugang zum Server |
| **Hardware** | Mindestens 2 GB RAM, 2 vCPUs, 20 GB SSD |
| **Software** | Docker + Docker Compose, Git |
| **Netzwerk** | Port 80 (HTTP) eingehend freigegeben |
| **Domain** | Optional — für HTTPS mit automatischem Zertifikat |

---

## Schritt 1: Docker installieren

### Option A: Docker Desktop (Server mit GUI)

1. Docker Desktop for Windows herunterladen:
   👉 https://docs.docker.com/desktop/setup/install/windows-install/
2. Installer ausführen → Neustart
3. Docker Desktop starten
4. Prüfen:

```powershell
docker --version
docker compose version
```

### Option B: Docker Engine via WSL2 (empfohlen für headless Server)

Für Windows Server ohne Desktop-Oberfläche ist Docker CE über WSL2 der empfohlene Weg:

```powershell
# WSL2 aktivieren und Ubuntu installieren
wsl --install -d Ubuntu
```

Nach dem Neustart in der WSL2-Ubuntu-Shell Docker installieren:

```bash
# In der WSL2-Shell (Ubuntu):
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER
```

> **Hinweis:** Bei Option B werden alle weiteren `docker compose`-Befehle in der WSL2-Shell ausgeführt.

---

## Schritt 2: Repository klonen

```powershell
# Zielverzeichnis erstellen
mkdir C:\Apps -ErrorAction SilentlyContinue
cd C:\Apps

# Repository klonen
git clone https://github.com/sincs99/haushalt-app.git
cd haushalt-app
```

> **Git nicht installiert?** → https://git-scm.com/download/win herunterladen und installieren.

---

## Schritt 3: Umgebungsvariablen konfigurieren

Die App liest ihre Konfiguration aus einer `.env`-Datei im Projektverzeichnis. Eine Vorlage ist vorhanden:

```powershell
Copy-Item .env.example .env
notepad .env
```

### Pflicht-Konfiguration

Die `.env`-Datei enthält drei Werte, die **alle angepasst werden müssen**:

```env
POSTGRES_PASSWORD=EinSicheresPasswort123!
JWT_SECRET_KEY=mindestens-32-zeichen-langer-zufallsstring-hier-einfuegen
CORS_ORIGINS=http://deine-server-ip
```

| Variable | Beschreibung | Beispielwert |
|---|---|---|
| `POSTGRES_PASSWORD` | Passwort für die PostgreSQL-Datenbank | `M3in$icher3sP@ssw0rt!` |
| `JWT_SECRET_KEY` | Geheimschlüssel für Auth-Tokens (min. 32 Zeichen) | *(siehe Generator unten)* |
| `CORS_ORIGINS` | URL, über die die App im Browser aufgerufen wird | `http://203.0.113.50` |

### JWT_SECRET_KEY generieren (PowerShell)

```powershell
[Convert]::ToBase64String((1..48 | ForEach-Object { Get-Random -Minimum 0 -Maximum 256 }) -as [byte[]])
```

Den ausgegebenen String in die `.env`-Datei als `JWT_SECRET_KEY` einfügen.

> ⚠️ **Sicherheitshinweis:** Die `.env`-Datei enthält Secrets und darf **niemals** ins Git-Repository committed werden. Sie ist bereits in `.gitignore` eingetragen.

---

## Schritt 4: App bauen und starten

```powershell
docker compose up --build -d
```

### Was passiert dabei?

Die [`docker-compose.yml`](../docker-compose.yml) definiert drei Services:

| # | Service | Was passiert |
|---|---|---|
| 1 | **postgres** | PostgreSQL 16 (Alpine) startet mit Healthcheck (`pg_isready`) |
| 2 | **backend** | Python 3.12 Container baut sich → wartet auf PostgreSQL → führt Alembic-Migrationen aus → startet Uvicorn auf Port 8000 |
| 3 | **frontend** | Node 22 baut das Vue-Frontend → Nginx serviert die statischen Dateien auf Port 80 |

Die Datenbank-Daten werden im Docker-Volume `pgdata` persistiert und überleben Container-Neustarts.

---

## Schritt 5: Prüfen ob alles läuft

```powershell
# Status aller Container anzeigen
docker compose ps

# Backend-Logs prüfen (Migrationen + Uvicorn-Start)
docker compose logs backend --tail 20

# Frontend-Logs prüfen (Nginx)
docker compose logs frontend --tail 10
```

### Erwartete Ausgabe von `docker compose ps`

```
NAME                    STATUS              PORTS
haushalt-app-postgres   Up (healthy)        0.0.0.0:5432->5432/tcp
haushalt-app-backend    Up                  0.0.0.0:8000->8000/tcp
haushalt-app-frontend   Up                  0.0.0.0:80->80/tcp
```

### App im Browser testen

Öffne im Browser:

```
http://<SERVER-IP>:80
```

Du solltest die Login-Seite der Haushalt-App sehen.

---

## Schritt 6: Windows Firewall konfigurieren

### Port 80 freigeben (HTTP)

```powershell
New-NetFirewallRule -DisplayName "Haushalt App HTTP" `
  -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow
```

### Optional: Port 443 freigeben (HTTPS)

```powershell
New-NetFirewallRule -DisplayName "Haushalt App HTTPS" `
  -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
```

### Cloud-Firewall nicht vergessen!

Wenn der Server bei einem Cloud-Provider läuft, muss Port 80 (und ggf. 443) **zusätzlich** in der Cloud-Firewall freigegeben werden:

| Provider | Wo konfigurieren |
|---|---|
| **Hetzner Cloud** | Firewall → Regel hinzufügen → TCP 80 Inbound |
| **Azure** | Network Security Group (NSG) → Inbound Security Rule |
| **AWS** | Security Group → Inbound Rule |

---

## Nützliche Befehle

| Befehl | Was passiert |
|---|---|
| `docker compose up -d` | Startet alle Container (im Hintergrund) |
| `docker compose down` | Stoppt alle Container |
| `docker compose restart` | Startet alle Container neu |
| `docker compose logs -f` | Live-Logs aller Container |
| `docker compose logs backend -f` | Live-Logs nur Backend |
| `docker compose logs frontend -f` | Live-Logs nur Frontend |
| `docker compose pull && docker compose up --build -d` | Update nach `git pull` |
| `docker compose exec postgres psql -U haushalt` | PostgreSQL-Shell öffnen |
| `docker compose exec backend alembic history` | Migrationshistorie anzeigen |

---

## Update-Workflow

Um die App auf den neuesten Stand zu bringen:

```powershell
cd C:\Apps\haushalt-app

# 1. Neueste Version holen
git pull origin master

# 2. Container neu bauen und starten
docker compose up --build -d
```

### Was passiert beim Update?

- Docker baut **nur geänderte Container** neu (Layer-Caching)
- Die **Datenbank bleibt erhalten** (Volume `pgdata` wird nicht angetastet)
- Alembic-Migrationen werden beim Backend-Start automatisch ausgeführt
- Kein manuelles Eingreifen nötig

> ⚠️ **Achtung:** Prüfe nach einem Update die Backend-Logs auf Migrationsfehler:
> ```powershell
> docker compose logs backend --tail 30
> ```

---

## Optional: HTTPS mit Caddy

Wenn eine Domain vorhanden ist (z.B. `haushalt.example.com`), kann für automatisches HTTPS ein [Caddy](https://caddyserver.com/)-Reverse-Proxy vorgeschaltet werden. Caddy holt sich automatisch ein Let's Encrypt Zertifikat.

### Ansatz

1. In [`docker-compose.yml`](../docker-compose.yml) einen Caddy-Service ergänzen
2. Caddy bedient Port 443 und leitet an den Frontend-Container (Port 80) weiter
3. Frontend-Port 80 nur noch intern exposen (nicht mehr auf dem Host)

### Beispiel Caddyfile

```
haushalt.example.com {
    reverse_proxy frontend:80
}
```

> **Hinweis:** Dies ist ein optionaler nächster Schritt und nicht im Basis-Setup enthalten. DNS muss auf die Server-IP zeigen, damit Let's Encrypt das Zertifikat ausstellen kann.

---

## Troubleshooting

| Problem | Lösung |
|---|---|
| **"Port 80 already in use"** | IIS oder anderen Webserver stoppen: `Stop-Service W3SVC` |
| **Backend-Container startet nicht** | `docker compose logs backend` prüfen → meistens fehlende DB-Verbindung oder Migrationsfehler |
| **"CORS error" im Browser** | `CORS_ORIGINS` in `.env` muss die exakte URL enthalten, über die du zugreifst (z.B. `http://203.0.113.50`) |
| **Migrationen schlagen fehl** | `docker compose logs backend` → Alembic-Fehlermeldung prüfen. Bei Schema-Konflikten: `docker compose exec backend alembic history` |
| **Frontend zeigt weisse Seite** | `docker compose logs frontend` → Nginx-Fehler prüfen. Häufig: Build-Fehler im Frontend-Container |
| **DB-Daten verschwunden** | `docker compose down` **ohne** `-v` Flag verwenden! Das `-v` Flag löscht alle Volumes inkl. Datenbank |
| **Docker Compose nicht gefunden** | Ältere Docker-Versionen: `docker-compose` (mit Bindestrich) statt `docker compose` verwenden |
| **Container starten, aber App nicht erreichbar** | Windows Firewall + Cloud-Firewall prüfen (siehe [Schritt 6](#schritt-6-windows-firewall-konfigurieren)) |

### Logs effizient lesen

Bei Problemen immer in dieser Reihenfolge vorgehen:

```powershell
# 1. Sind alle Container oben?
docker compose ps

# 2. PostgreSQL gesund?
docker compose logs postgres --tail 10

# 3. Backend-Start erfolgreich? (Migrationen + Uvicorn)
docker compose logs backend --tail 30

# 4. Frontend/Nginx ok?
docker compose logs frontend --tail 10
```

---

## Architektur-Übersicht

```
                    ┌──────────────────────────────────┐
                    │        Windows Server             │
                    │                                   │
  Browser ──────►  │  ┌──────────┐    ┌──────────┐     │
  (Port 80)        │  │ Frontend │    │ Backend  │     │
                    │  │ (Nginx)  │◄──►│ (Uvicorn)│     │
                    │  │ :80      │    │ :8000    │     │
                    │  └──────────┘    └────┬─────┘     │
                    │                       │           │
                    │                  ┌────▼─────┐     │
                    │                  │ Postgres │     │
                    │                  │ :5432    │     │
                    │                  │ (pgdata) │     │
                    │                  └──────────┘     │
                    └──────────────────────────────────┘
```

**Datenfluss:**
1. Browser → Nginx (Frontend, statische Dateien + SPA-Routing)
2. Frontend JS → Backend API (Uvicorn, Port 8000)
3. Backend → PostgreSQL (Datenbank, Port 5432)
