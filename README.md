# haushalt-app

[![CI](https://github.com/sincs99/haushalt-app/actions/workflows/ci.yml/badge.svg)](https://github.com/sincs99/haushalt-app/actions/workflows/ci.yml)

Web-App (PWA) für die gemeinsame Organisation eines Haushalts: Einkaufslisten, Aufgaben, Putzplan mit Ämtli-Rotation, Ausgaben-Teilung mit Ausgleichszahlungen, Budget und wiederkehrende Rechnungen, Kalender mit Abstimmungen, Essensplanung, Haustiere, Notizen und eine Dokument-Ablage (Verträge, Rechnungen, Garantien). Mehrere Nutzer pro Haushalt, Echtzeit-Sync per WebSocket, Mobile-First, zweisprachig (DE/EN).

Detaillierter Stand und Architektur: [`docs/PROJECT-STATUS.md`](docs/PROJECT-STATUS.md).

## Tech-Stack

| Bereich | Technologie |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Socket.IO (`python-socketio`) |
| Datenbank | PostgreSQL 16 |
| Frontend | Vue 3, TypeScript, Vite, Pinia, vue-i18n, PWA (`vite-plugin-pwa`) |
| Auth | JWT-Access-Token (15 Min.) + rotierender Refresh-Token, bcrypt |
| Tests | Backend: pytest (SQLite in-memory, kein Postgres nötig); Frontend: Vitest |
| Betrieb | Docker Compose (Dev und Produktion hinter Nginx Proxy Manager) |

Exakte Versionen: `backend/requirements.txt` und `frontend/package-lock.json`.

## Schnellstart mit Docker

```bash
cp .env.example .env
# In .env zwei Pflichtwerte setzen (ohne sie startet docker compose nicht):
#   POSTGRES_PASSWORD und JWT_SECRET_KEY
#   Zufallswert erzeugen: python -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose up -d --build
```

Die App läuft danach unter <http://localhost:8080> (anderer Port: `FRONTEND_PORT` in `.env`). Datenbank (5432) und Backend (8000) sind nur vom Rechner selbst erreichbar (`127.0.0.1`). Die Datenbank-Migrationen laufen beim Start des Backend-Containers automatisch (`alembic upgrade head`).

Weitere Einstellungen stehen kommentiert in [`.env.example`](.env.example), darunter Web Push (VAPID-Schlüssel) und das Speicher-Limit pro Haushalt für Uploads (`HOUSEHOLD_STORAGE_QUOTA_MB`).

## Lokale Entwicklung ohne Docker

Voraussetzungen: Python 3.12, Node.js 22, eine PostgreSQL-Datenbank.

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://USER:PASSWORT@localhost:5432/haushalt
export JWT_SECRET_KEY=...                            # mindestens 32 Zeichen, kein Platzhalter
export CORS_ORIGINS=http://localhost:5173
alembic upgrade head
uvicorn app.main:app --reload --port 8000            # API-Doku: http://localhost:8000/docs

# Frontend (zweites Terminal)
cd frontend
npm ci
npm run dev                                          # http://localhost:5173, Proxy auf Port 8000
```

## Prüfungen (wie in der CI)

Die CI (`.github/workflows/ci.yml`) führt bei jedem Push auf `master` und bei jedem Pull Request aus:

```bash
# Backend (im Ordner backend/)
pip install -r requirements.txt pytest httpx pytest-cov ruff
ruff check .
pytest -q --cov=app

# Frontend (im Ordner frontend/)
npm ci
npm run check:locales      # DE/EN-Schlüssel müssen übereinstimmen
npm run typecheck
npm run test:coverage

# Abhängigkeiten auf bekannte Schwachstellen prüfen
pip install pip-audit && pip-audit -r backend/requirements.txt
cd frontend && npm audit --omit=dev --audit-level=high
```

Die Backend-Tests setzen `DATABASE_URL`, `JWT_SECRET_KEY` und `CORS_ORIGINS` selbst und brauchen keine laufende Datenbank. Wer `DATABASE_URL` in der Shell gesetzt hat, sollte sie vor `pytest` entfernen, sonst laufen die Tests gegen diese Datenbank.

## Produktion

- [`docs/deployment.md`](docs/deployment.md): Docker-Deployment hinter Nginx Proxy Manager, Updates, Rollback, Web Push
- [`docs/DEPLOYMENT-WINDOWS-SERVER.md`](docs/DEPLOYMENT-WINDOWS-SERVER.md): Einrichtung auf einem Windows-Server
- [`docs/security/`](docs/security/): Sicherheits-Reviews (zuletzt `hardening-review.md`)
- [`docs/offline-first-phase2.md`](docs/offline-first-phase2.md): Konzept für Offline-Betrieb (Meilenstein M0 ist umgesetzt)

## Datensicherung

### Backup erstellen

```powershell
.\scripts\backup-db.ps1
```

Erstellt einen komprimierten Datenbank-Dump unter `backups/casa-backup-<Zeitstempel>.dump` **und** ein Archiv der hochgeladenen Dateien (Dokument-Ablage, Tierfotos) unter `backups/casa-uploads-<Zeitstempel>.tar.gz`.  
Es werden automatisch maximal **14 Backups** vorgehalten; ältere werden gelöscht. Beide Container (Postgres und Backend) müssen laufen.

### Backup wiederherstellen

```powershell
.\scripts\restore-db.ps1 -DumpFile .\backups\casa-backup-2025-01-15_14-30.dump
```

Das passende Uploads-Archiv wird mit wiederhergestellt (oder explizit mit `-UploadsFile`). Das Skript fragt vor dem Überschreiben der Datenbank nach einer Bestätigung.  
Nach dem Restore empfiehlt es sich, das Backend neu zu starten:

```powershell
docker compose restart backend
```

### ⚠️ Wichtige Warnungen

**`docker compose down -v` und `docker volume rm` LÖSCHEN ALLE DATEN unwiderruflich!**  
**Verwende NIEMALS `-v` bei `docker compose down`, es sei denn, du hast ein aktuelles Backup.**

### Empfohlene Backup-Regeln

1. **Vor jedem `alembic upgrade`** ein Backup erstellen
2. **Wöchentlich** manuell ein Backup erstellen
3. Backup-Datei zusätzlich in einen **Cloud-Speicher** (z.B. OneDrive, Google Drive) kopieren
4. **Nach der Ersteinrichtung** einmal den kompletten Zyklus testen: Backup erstellen → Restore ausführen → App prüfen
