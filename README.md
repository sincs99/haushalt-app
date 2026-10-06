# haushalt-app

[![CI](https://github.com/sincs99/haushalt-app/actions/workflows/ci.yml/badge.svg)](https://github.com/sincs99/haushalt-app/actions/workflows/ci.yml)

Web-App (PWA) für die gemeinsame Organisation eines Haushalts: Einkaufslisten, Aufgaben, Putzplan mit Ämtli-Rotation, Ausgaben-Teilung mit Ausgleichszahlungen, Budget und wiederkehrende Rechnungen, Kalender mit Abstimmungen, Essensplanung, Haustiere, Pflanzen, Notizen, eine Dokument-Ablage (Verträge, Rechnungen, Garantien), NFC/QR-Tags für Ein-Tipp-Aktionen und ein optionaler KI-Assistent (Rezeptvorschläge, Pflanzenpflege). Mehrere Nutzer pro Haushalt, Echtzeit-Sync per WebSocket, Mobile-First, zweisprachig (DE/EN).

Detaillierter Stand und Architektur: [`docs/PROJECT-STATUS.md`](docs/PROJECT-STATUS.md).

## Tech-Stack

| Bereich | Technologie |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Socket.IO (`python-socketio`) |
| Datenbank | PostgreSQL 16 |
| Frontend | Vue 3, TypeScript, Vite, Pinia, vue-i18n, PWA (`vite-plugin-pwa`) |
| Auth | JWT-Access-Token (15 Min.) + rotierender Refresh-Token als HttpOnly-Cookie, bcrypt |
| KI (optional) | Anthropic-API (Claude Opus 5.5) über das offizielle `anthropic`-SDK |
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

Weitere Einstellungen stehen kommentiert in [`.env.example`](.env.example), darunter Web Push (VAPID-Schlüssel), das Speicher-Limit pro Haushalt für Uploads (`HOUSEHOLD_STORAGE_QUOTA_MB`) und der optionale KI-Assistent (`ANTHROPIC_API_KEY`, siehe unten).

## KI-Assistent (optional)

Rezeptvorschläge aus vorhandenen Zutaten und Pflanzenpflege-Hinweise über die Anthropic-API (Modell Claude Opus 5.5, offizielles `anthropic`-SDK). Ohne Schlüssel sind alle KI-Funktionen ausgeblendet und die App läuft unverändert.

| Variable | Standard | Bedeutung |
|---|---|---|
| `ANTHROPIC_API_KEY` | leer | API-Schlüssel (<https://console.anthropic.com>); leer = KI deaktiviert |
| `AI_DAILY_LIMIT_PER_HOUSEHOLD` | `50` | KI-Aufrufe pro Haushalt und Tag (UTC), danach HTTP 429 |
| `AI_REQUEST_TIMEOUT_SECONDS` | `90` | Timeout pro Versuch (das SDK wiederholt höchstens einmal) |
| `AI_MAX_CONCURRENT_REQUESTS` | `4` | gleichzeitige KI-Aufrufe pro Backend-Prozess |

Eintragen in `.env` (Docker-Dev) bzw. `.env.prod` (Produktion). Der Schlüssel bleibt im Backend; das Frontend ruft den Anbieter nie direkt. Zusätzlich muss ein **Admin den Assistenten pro Haushalt einschalten** (Einstellungen → KI-Assistent); dort steht auch der Hinweis, dass Eingaben (Zutaten, Pflanzenart) an die Anthropic-API gesendet werden. Pro Aufruf gilt ausserdem ein IP-Limit von 10/min.

Liegt Nginx Proxy Manager davor: für den Host ein längeres Timeout eintragen (`proxy_read_timeout 200s;`), Rezeptvorschläge können länger als 60 s dauern.

Architektur, Datenfluss, Kosten und Ausgabe-Schemas: [`docs/ai-assistant.md`](docs/ai-assistant.md). Sicherheitsbewertung: [`docs/security/ai-assistant-review.md`](docs/security/ai-assistant-review.md).

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

Die Backend-Tests setzen `DATABASE_URL`, `JWT_SECRET_KEY` und `CORS_ORIGINS` selbst und brauchen keine laufende Datenbank. Die Tests des KI-Assistenten mocken den Anthropic-Client und brauchen keinen API-Schlüssel. Wer `DATABASE_URL` in der Shell gesetzt hat, sollte sie vor `pytest` entfernen, sonst laufen die Tests gegen diese Datenbank.

## Produktion

- [`docs/deployment.md`](docs/deployment.md): Docker-Deployment hinter Nginx Proxy Manager, Updates, Rollback, Web Push
- [`docs/DEPLOYMENT-WINDOWS-SERVER.md`](docs/DEPLOYMENT-WINDOWS-SERVER.md): Einrichtung auf einem Windows-Server
- [`docs/security/`](docs/security/): Sicherheits-Reviews (zuletzt `ai-assistant-review.md`)
- [`docs/qa/logic-review.md`](docs/qa/logic-review.md): Logik-Review der Geschäftsregeln (Szenarien pro Modul, behobene Fehler, offene Produktentscheidungen)
- [`docs/ai-assistant.md`](docs/ai-assistant.md): KI-Assistent (Architektur, Datenschutz, Kosten, Erweiterung)
- [`docs/offline-first-phase2.md`](docs/offline-first-phase2.md): Konzept für Offline-Betrieb (Meilenstein M0 ist umgesetzt)

## Tags (NFC/QR)

Tags sind NFC-Chips oder QR-Sticker, die beim Scannen eine Aktion mit einem Tipp auslösen: Tier füttern, Pflanze gießen, Pflegeaufgabe oder Ämtli abhaken, Aufgabe erledigen, Einkaufsliste öffnen. Auf dem Tag steht nur eine Adresse der App, `https://<host>/t/<token>`. Welche Aktion dazugehört, steht in der Datenbank — ein Tag lässt sich deshalb später neu zuordnen, ohne ihn neu zu beschreiben.

**Ablauf beim Scannen:** Das Telefon öffnet die Adresse. Wer nicht eingeloggt ist, landet beim Login und danach wieder auf dem Tag. Die App zeigt eine Bestätigung (z. B. „Mia füttern?“ mit der letzten Fütterung oder „Monstera gegossen?“ mit letzter Gießung und nächster Fälligkeit); erst der Tipp auf den grossen Button führt die Aktion aus. Tags zum Öffnen einer Liste navigieren direkt. Ausführen dürfen alle Mitglieder des Haushalts, Fremde mit dem Sticker in der Hand nichts.

**Beispiel Pflanze:** Der Sticker am Blumentopf (Zieltyp „Pflanze“, Aktion „Pflanze gießen“) trägt die Gießaufgabe der Pflanze ein; nach dem Scan führt „Ansehen“ auf die Pflanze. Ohne Ziel gewählt, giesst der Tag alle heute fälligen Pflanzen auf einmal. Wer lieber eine einzelne Aufgabe abhakt (Düngen, Umtopfen), nimmt „Pflanzenpflege“ mit der Pflegeaufgabe als Ziel.

**Einrichten (Admin):** Haushalt → „Tags verwalten“ → „Tag anlegen“: Bezeichnung, Zieltyp, Ziel und Aktion wählen. Danach zeigt die App QR-Code, Adresse und — auf Android/Chrome — „Auf NFC-Chip schreiben“.

### Welche Chips?

- **NTAG213** (144 Byte Nutzspeicher) reicht: Die Adresse ist der Hostname plus `/t/` plus 32 Zeichen Token, zusammen meist unter 70 Byte. **NTAG215** (504 Byte) oder **NTAG216** (888 Byte) gehen ebenfalls.
- Bauform nach Ort: Sticker für glatte Flächen, **On-Metal-/Anti-Metall-Tags** für Kühlschrank, Metallnapf oder Heizkörper (normale Chips funktionieren auf Metall nicht), Schlüsselanhänger oder Epoxy-Tags für feuchte Orte.
- Nicht geeignet: MIFARE Classic (wird von iPhones nicht gelesen).

### Chips beschreiben

- **Android mit Chrome:** In der App „Auf NFC-Chip schreiben“ tippen und den Chip an die Rückseite halten (Web NFC, nur Chrome auf Android, nur über HTTPS).
- **iPhone und andere Browser:** Mit einer NFC-App, z. B. „NFC Tools“ (iOS/Android): „Schreiben“ → „Datensatz hinzufügen“ → „URL/URI“ → die in der App angezeigte Adresse einfügen → „Schreiben“. Genau **einen** URL-Datensatz schreiben.
- **Optional sperren:** In der NFC-App „Tag sperren/Lock“ verhindert, dass jemand den Chip überschreibt. Das ist endgültig — nach „Token neu erzeugen“ braucht es dann einen neuen Chip.
- **QR-Sticker:** QR-Code als SVG herunterladen und drucken, ab etwa 2 × 2 cm zuverlässig lesbar.

### Verhalten auf den Geräten

- **iPhone (ab XS):** liest NFC-Chips im Hintergrund, ohne App; es erscheint eine Mitteilung, ein Tipp öffnet die Adresse in Safari. QR-Codes liest die Kamera-App. Die als Web-App installierte Version auf dem Home-Bildschirm hat einen **eigenen Login-Speicher** — Tags öffnen Safari, dort muss man sich einmal separat anmelden.
- **Android:** liest NFC-Chips bei entsperrtem Bildschirm, ohne App. Ist die App über Chrome installiert, öffnen sich Adressen der App in der Regel direkt in der installierten App (sonst in Chrome, der Login gilt dort ebenfalls). QR-Codes liest die Kamera oder Google Lens.
- **Sicherheit:** Ein Tag bewirkt nichts ohne Login als Mitglied des Haushalts. Ist ein Sticker verloren oder abfotografiert: „Token neu erzeugen“ — der alte Tag ist danach wirkungslos. Details: [`docs/security/tags-review.md`](docs/security/tags-review.md).

## Datensicherung

### Backup erstellen

```powershell
.\scripts\backup-db.ps1
```

Erstellt einen komprimierten Datenbank-Dump unter `backups/casa-backup-<Zeitstempel>.dump` **und** ein Archiv der hochgeladenen Dateien (Dokument-Ablage, Tier- und Pflanzenfotos) unter `backups/casa-uploads-<Zeitstempel>.tar.gz`.  
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
