# Haushalt-App — Gemeinsame Haushaltsorganisation

Eine moderne Web-App für gemeinsame Einkaufslisten, Aufgabenverwaltung, Putzplan mit Ämtli-Rotation, Ausgaben-Teilung und mehr. Entwickelt mit Python/FastAPI Backend und Vue 3/TypeScript Frontend.

## Tech Stack

| Bereich | Technologien |
|---------|--------------|
| **Backend** | Python 3.12+, FastAPI 0.141, SQLAlchemy ORM, Alembic Migrations |
| **Datenbank** | PostgreSQL (psycopg2) |
| **Realtime** | Socket.IO (WebSocket) |
| **Frontend** | Vue 3.5, TypeScript 5.8, Vite 8, Pinia 4 |
| **State Mgmt** | Pinia (Composition API) |
| **HTTP Client** | Axios mit JWT Interceptor |
| **Authentication** | JWT (Bearer Tokens), bcrypt Password Hashing |
| **Internationalisierung** | vue-i18n (DE/EN, 631 Keys) |
| **UI Components** | Custom Design-System, Phosphor Icons |
| **PWA** | vite-plugin-pwa, Web Push Ready |
| **Testing** | Backend: pytest (41 test files), Frontend: Vitest |
| **Deployment** | Docker Compose (dev + prod), PostgreSQL in Docker |

## Lokal Starten

### Voraussetzungen

- Docker & Docker Compose
- Optional: Python 3.12+ und Node.js 22+ (für direkte Installation)

### Backend (Python/FastAPI)

```bash
# 1. In den Backend-Ordner wechseln
cd backend

# 2. Virtual Environment erstellen (optional, für direkte Python-Nutzung)
python -m venv venv
source venv/bin/activate  # oder: venv\Scripts\activate (Windows)

# 3. Dependencies installieren
pip install -r requirements.txt

# 4. .env Datei erstellen (siehe .env.example)
cp .env.example .env
# .env anpassen: DATABASE_URL, JWT_SECRET, etc.

# 5. Datenbank-Migrationen ausführen
alembic upgrade head

# 6. Backend starten
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Die API läuft dann unter `http://localhost:8000`. API-Docs: `http://localhost:8000/docs`

### Frontend (Vue 3/TypeScript)

```bash
# 1. In den Frontend-Ordner wechseln
cd frontend

# 2. Dependencies installieren
npm ci

# 3. Dev-Server starten
npm run dev
```

Die App läuft dann unter `http://localhost:5173` (Vite default).

### Mit Docker Compose (empfohlen)

```bash
# Development
docker compose up

# oder für Production
docker compose -f docker-compose.prod.yml up
```

Backend läuft auf `http://localhost:8000`, Frontend auf `http://localhost:3000`.

## Tests & Checks

### Backend

```bash
cd backend

# pytest mit Dependencies installieren (falls noch nicht geschehen)
pip install pytest httpx

# Tests ausführen
pytest -q

# Alle Tests mit Ausgabe
pytest -v
```

### Frontend

```bash
cd frontend

# i18n Key-Sync prüfen (DE/EN müssen identisch sein)
npm run check:locales

# TypeScript Type-Checking
npm run typecheck

# Unit Tests (Vitest)
npm test
```

## Dokumentation

Siehe `docs/` für weitere Informationen:
- [`docs/PROJECT-STATUS.md`](docs/PROJECT-STATUS.md) — Detaillierter Projektstand, Architektur, Feature-Liste, Epics
- [`docs/deployment.md`](docs/deployment.md) — Produktions-Deployment Setup
- [`docs/offline-ready-architecture.md`](docs/offline-ready-architecture.md) — Offline-First Architektur & Phase 2 Planung
- `docs/security/` — Security Reviews für einzelne Module

## Datensicherung

### Backup erstellen

```powershell
.\scripts\backup-db.ps1
```

Erstellt einen komprimierten Datenbank-Dump unter `backups/casa-backup-YYYY-MM-DD_HH-mm.dump`.  
Es werden automatisch maximal **14 Backups** vorgehalten; ältere werden gelöscht.

### Backup wiederherstellen

```powershell
.\scripts\restore-db.ps1 -DumpFile .\backups\casa-backup-2025-01-15_14-30.dump
```

Das Skript fragt vor dem Überschreiben der Datenbank nach einer Bestätigung.  
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
