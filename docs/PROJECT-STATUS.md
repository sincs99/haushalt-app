# Haushalt-App — Aktueller Projektstand

**Stand:** 2026-10-07 (Audit-Korrekturen, aktuelle lokale Test- und Locale-Zahlen, HEIC/HEIF und Build-Prüfung nachgeführt; die OpenAPI-Doku des Backends unter `/docs` bleibt für API-Details maßgeblich)
**Autor:** Tech Lead (automatisch generiert)

---

## 1. Projektübersicht

Eine Haushalt-App für gemeinsame Einkaufslisten, Aufgaben, wiederkehrende Putzpläne mit Ämtli-Rotation, Ausgaben-Teilung mit Ausgleichszahlungen, Budget und wiederkehrende Rechnungen, Kalender mit Abstimmungen, Essensplanung, Haustiere, Pflanzen, Notizen und eine Dokument-Ablage (Verträge, Rechnungen, Garantien) innerhalb eines Haushalts. Multi-User, Echtzeit-Sync via WebSocket, Mobile-First UI, installierbare PWA mit Web Push, zweisprachig (DE/EN). Optional dazu ein KI-Assistent (Rezeptvorschläge, Pflanzenpflege-Hinweise) über die Anthropic-API, nur mit Server-Schlüssel und Opt-in des Haushalts.

| Aspekt | Technologie |
|---|---|
| Backend | Python 3.12+, FastAPI 0.141, SQLAlchemy, Alembic |
| Datenbank | PostgreSQL (via psycopg2) |
| Realtime | Socket.IO (python-socketio) |
| Frontend | Vue 3.5, TypeScript 5.8, Vite 8, Pinia 4, PWA (`vite-plugin-pwa`) |
| Auth | JWT-Access-Token (15 Min., nur im Speicher) + rotierender Refresh-Token als HttpOnly-Cookie (`SameSite=Strict`, CSRF-Header) mit Reuse-Erkennung, bcrypt-Hashing |
| i18n | vue-i18n, 1173 Keys (DE + EN), Build-gesicherter Key-Sync |
| KI (optional) | Anthropic-API (`claude-opus-5-5`) über das offizielle `anthropic`-SDK, Structured Outputs; ohne `ANTHROPIC_API_KEY` ausgeblendet |
| Qualität / CI | GitHub Actions: Backend (ruff, pytest mit Coverage), Backend auf PostgreSQL 16 (`alembic upgrade head`, pg-Testlane, Downgrade/Upgrade), Frontend (Locale-Check, Typecheck, Vitest mit Coverage), Dependency-Audit (pip-audit, npm audit) |
| Betrieb | Docker Compose (Dev und Produktion hinter Nginx Proxy Manager), Backup-Skripte für Datenbank und Uploads |
| Icons | Phosphor Icons (`@phosphor-icons/vue`) — regular/fill/bold |
| UI | Custom Design-System (CSS Custom Properties, Nunito + Quicksand), Mobile-First |

### Änderungen seit 2026-08-12

Alle Änderungen kamen per Pull Request auf `master`:

| PR | Inhalt |
|---|---|
| #6 | CI-Pipeline (GitHub Actions) mit Backend- und Frontend-Job, Status-Badge in der README |
| #8 | Sicherheit/Betrieb: Rate-Limit-Umgehung per gefälschtem `X-Forwarded-For` behoben, Pfade für wiederkehrende Rechnungen hinter HTTPS, Pflicht-Secrets und lokal gebundene Ports in den Compose-Dateien, Backup inkl. Uploads (und Bugfix im Backup-Skript) |
| #9 | Datenkorrektheit: Ämtli-Rotation springt beim Umbenennen nicht mehr, Kalender-Uhrzeiten in der Haushalts-Zeitzone (inkl. Migration bestehender Termine), doppelte Teilnehmer bei Ausgaben abgelehnt, Ausgleich mit Ex-Mitgliedern, Standard-Zahler bei wiederkehrenden Rechnungen |
| #10 | DB-Integrität: Löschregeln (`ondelete`), eine Stimme pro Person und Abstimmung, eine Buchung pro Rechnung und Monat, `household_id`-Indizes, Test gegen mehrere Alembic-Köpfe |
| #11 | Mitglieder-Lebenszyklus: Entfernte Mitglieder verlassen den Echtzeit-Raum, Einladungscode wird beim Entfernen erneuert (und ist per Admin-Button erneuerbar), Dateien werden beim Löschen eines Haushalts entfernt |
| #7 | Dokument-Ablage (Backend, Ansicht, mehrseitige Dokumente, Speicher-Limit pro Haushalt) sowie Schließen der Upload-Befunde F-02 bis F-04 |
| #12 | Offline-first: Konzeptdokument (`docs/offline-first-phase2.md`) und Meilenstein M0 (vom Client erzeugte IDs, `updated_at`/`version`, idempotentes Anlegen) |
| #13 | Security-Hardening: HTTP-Security-Header und CSP, engeres CORS, Rate-Limits für Refresh/Logout/Beitritt, Dependency-Audit-Job, Review `docs/security/hardening-review.md` |
| #14 | Abhängigkeits-Updates gegen bekannte Schwachstellen (u. a. Pillow 12, cryptography 50, PyJWT 2.15) |
| #15 | ruff im Backend, Coverage-Berichte, Unit-Tests für Utils und vier Stores |
| #16 | Doku: README neu geschrieben, dieser Projektstand aktualisiert, Hardening-Review nachgeführt |
| #17 | Frontend-Stores: Geschäfts-Filter folgt dem Umbenennen, fehlgeschlagenes Löschen eines Ämtlis stellt dessen Zuweisungen wieder her; Unit-Tests für den Auth-Store |
| #18 | Einkauf: Geschäftsnamen werden ohne Beachtung der Groß-/Kleinschreibung zusammengeführt (Backend und Frontend, keine Migration); bestehende Einträge behalten ihre Schreibweise |
| Branch `claude/nfc-qr-tags` | Tags (NFC-Chips/QR-Sticker) mit Ein-Tipp-Aktionen: Füttern, Pflegeaufgabe, Ämtli, Todo abhaken, Einkaufsliste öffnen; Verwaltung mit QR-Code und Web NFC; Review `docs/security/tags-review.md` (Epic 32) |
| Branch `claude/plants-ai-tags-integration` | Pflanzen × KI × Tags: KI-Pflegehinweise im Pflanzen-Formular und in der Detailansicht; Tag-Aktionen `plant.water` und `plant.care_task.done` (Epic 34) |
| Branch `claude/ai-assistant` | KI-Assistent Etappe 1: Rezeptvorschlag und Pflanzenpflege, Opt-in pro Haushalt, Tageslimit; Rezepte erhalten Zubereitungsschritte und Tags (Epic 33, `docs/ai-assistant.md`) |
| Branch `claude/logic-review` | Logik-Review der Geschäftsregeln (`docs/qa/logic-review.md`): Kalenderdaten der Finanzen in Haushaltszeit (`services/household_time.py`), gebuchte Rechnungen immer `even`, `decide` sendet den vollständigen Termin, Dashboard zählt heute fällige Todos nicht als überfällig, Ämtli mit Ex-Mitglied in der Rotation bleibt bearbeitbar, Tierpflege-Erinnerung nach Verschieben der Fälligkeit, Haushaltswechsel leert alle Stores, Rolle nach Auto-Beförderung wird sofort geladen; 10 offene Produktentscheidungen |

**Kennzahlen (lokaler Reparaturstand vom 7. Oktober 2026):** Backend 837 Tests in 62 Dateien, Coverage 94 %; Frontend 473 Tests in 33 Dateien, Coverage 77,49 % (Statements), 72,14 % (Branches), Statement-Schwelle 66 %; 1173 i18n-Schlüssel; 37 Alembic-Migrationen (einziger Kopf `y1z2a3b4c5d6`).

Korrekturen und Prüfnachweise: [Audit vom 7. Oktober 2026](qa/current-audit-fixes.md). App-Typprüfung und Produktionsbuild bestehen; Chromium und WebKit wurden lokal geprüft. Produktion und das echte iPhone bleiben ungeprüft. Für den HEIC/HEIF-Serverfallback sind passende Frontend- und Backend-Builds mit `pillow-heif==1.8.0` erforderlich; keine neue Datenbankmigration.


**Neue Bausteine (Auswahl):** Router `documents`, `files`, `push`, `plants`, `tags`, `ai`; Services `client_ids`, `event_times`, `file_cleanup`, `push_service`; Ansichten `DocumentsView`, `PetsView`/`PetDetailView`, `PlantsView`/`PlantDetailView`, `FoodView`, `NotesView`, `CalendarView`, `DashboardView`; Repositories und Stores für Dokumente, Haustiere, Pflanzen, Essen, Notizen, Kalender und Finanzen.

---

## 2. Architektur

```
┌─────────────────────────────────────────────────────┐
│                    Vue 3 Frontend                     │
│                                                       │
│  Views → Components → Pinia Stores → Repositories     │
│                           ↕                ↓           │
│                     Socket.IO        Axios (REST)      │
└──────────────────────┬────────────────────────────────┘
                       │
                HTTPS / WSS
                       │
┌──────────────────────▼────────────────────────────────┐
│                  FastAPI Backend                        │
│                                                        │
│  Routers (auth, shopping, todos, households,            │
│           expenses, settlements, chores)                │
│      ↓              ↓                                  │
│  SQLAlchemy    Socket.IO Server                        │
│      ↓                                                 │
│  PostgreSQL                                            │
└────────────────────────────────────────────────────────┘
```

---

## 3. Datei-Übersicht

### Backend (`backend/`)

| Datei | Zweck | Status |
|---|---|---|
| [`app/main.py`](../backend/app/main.py) | FastAPI-App (`redirect_slashes=False`), Startup-Prüfung der Konfiguration, CORS, Security-Header-Middleware, Rate-Limit-Handler, Mount aller 23 Router, Socket.IO-Mount unter `/socket.io`, `GET /api/health` (mit DB-Check), Hintergrund-Tasks (Web-Push-Scheduler, Upload-Cleanup) | ✅ Fertig |
| [`app/models.py`](../backend/app/models.py) | SQLAlchemy-Models (32 Tabellen, siehe Abschnitt 5) und `SyncVersionMixin` (`updated_at`/`version`) | ✅ Fertig |
| [`app/database.py`](../backend/app/database.py) | DB-Session, Engine, Base | ✅ Fertig |
| [`app/socket_manager.py`](../backend/app/socket_manager.py) | Socket.IO-Server: JWT-Auth beim Verbindungsaufbau, Haushalt-Räume (`join_household` prüft Mitgliedschaft), persönlicher Raum pro User, Sitzungs-Ablauf (Timer + `reauth`), `emit_to_household(_sync)` inkl. Rauswurf entfernter Mitglieder, `disconnect_user_sync` | ✅ Fertig |
| [`app/core/config.py`](../backend/app/core/config.py) | Pydantic Settings (DB-URL, JWT-Secret, CORS, Token-Laufzeiten, Umgebung, VAPID-Schlüssel, Speicher-Limit pro Haushalt) | ✅ Fertig |
| [`app/core/security.py`](../backend/app/core/security.py) | Access-/Refresh-Token-Erzeugung, Passwort-Hashing/-Verify (bcrypt), Invite-Code-Generierung | ✅ Fertig |
| [`app/core/deps.py`](../backend/app/core/deps.py) | Dependencies: `get_current_user`, `verify_household_access`, `verify_household_admin` | ✅ Fertig |
| [`app/core/error_codes.py`](../backend/app/core/error_codes.py) | Maschinenlesbare Error-Codes (`ErrorCode`, `error_detail`) | ✅ Fertig |
| [`app/core/db_errors.py`](../backend/app/core/db_errors.py) | Globale Handler: `IntegrityError`, `StaleDataError`, PG-Deadlock/Serialisierung/Lock-Timeout → 409 `CONFLICT_RETRY` (Safety-Net; `get_db` rollt zurück) | ✅ Fertig |
| [`app/core/patch_schema.py`](../backend/app/core/patch_schema.py) | `PatchModel`: Basis aller `*Update`-Schemas — explizites `null` auf NOT-NULL-Spalten (aus dem ORM-Modell abgeleitet) → 422 | ✅ Fertig |
| [`app/core/rate_limit.py`](../backend/app/core/rate_limit.py) | Zentraler `slowapi`-Limiter (pro IP, im Speicher; Client-IP aus `X-Forwarded-For` des Proxys) | ✅ Fertig |
| [`app/core/security_headers.py`](../backend/app/core/security_headers.py) | ASGI-Middleware: HTTP-Security-Header (u. a. CSP) für alle API-Antworten | ✅ Fertig |
| [`app/routers/auth.py`](../backend/app/routers/auth.py) | 5 Endpoints: register, login, refresh, logout, me (mit Rate-Limits) | ✅ Fertig |
| [`app/routers/households.py`](../backend/app/routers/households.py) | 9 Endpoints: Haushalt erstellen/umbenennen/beitreten/verlassen, Mitglieder, Einladungscode (anzeigen/erneuern, mit Ablaufdatum), Mitglied entfernen, Finanz-Zusammenfassung; Beitritt mit Rate-Limit | ✅ Fertig |
| [`app/routers/shopping.py`](../backend/app/routers/shopping.py) | 10 Endpoints: Einkaufslisten (`list_router`) und Einkaufseinträge inkl. Geschäfts-Verwaltung (`router`) + Socket-Events | ✅ Fertig |
| [`app/routers/todos.py`](../backend/app/routers/todos.py) | 7 Endpoints: Todos (CRUD, Claim) und Erinnerungen + Socket-Events | ✅ Fertig |
| [`app/routers/expenses.py`](../backend/app/routers/expenses.py) | 7 Endpoints: Ausgaben (CRUD, Split even/custom, Einzelabruf, Wiederherstellen) und Salden; Zeilensperre + `version`/`If-Match` (409 `EXPENSE_VERSION_CONFLICT`), Soft Delete mit `created_by`/`updated_by`/`deleted_by`, Flag `before_last_settlement`; Pydantic-Schemas inline | ✅ Fertig |
| [`app/routers/settlements.py`](../backend/app/routers/settlements.py) | 3 Endpoints: Ausgleichszahlungen (GET/POST/DELETE) + Socket-Events | ✅ Fertig |
| [`app/routers/chores.py`](../backend/app/routers/chores.py) | 8 Endpoints: Ämtli (CRUD) und Zuweisungen (Liste, abhaken, rückgängig, neu zuweisen) + Socket-Events | ✅ Fertig |
| [`app/routers/budgets.py`](../backend/app/routers/budgets.py) | 3 Endpoints: Monatsbudget (setzen, lesen, löschen) | ✅ Fertig |
| [`app/routers/recurring_bills.py`](../backend/app/routers/recurring_bills.py) | 5 Endpoints: wiederkehrende Rechnungen (CRUD, Buchen als Ausgabe; eine nicht gelöschte Buchung pro Rechnung und Monat; Nachbuchen bis 12 Monate zurück; nur `split_type` `even`) | ✅ Fertig |
| [`app/routers/calendars.py`](../backend/app/routers/calendars.py) | 4 Endpoints: Kalender (Name/Farbe/Position) | ✅ Fertig |
| [`app/routers/events.py`](../backend/app/routers/events.py) | 5 Endpoints: Termine (CRUD, Zeitraum-Abfrage in Haushaltszeit) | ✅ Fertig |
| [`app/routers/polls.py`](../backend/app/routers/polls.py) | 7 Endpoints: Abstimmungen (Termin- und Essens-Umfragen, Stimme, Entscheidung) | ✅ Fertig |
| [`app/routers/pets.py`](../backend/app/routers/pets.py) | 20 Endpoints: Haustiere, Fütterung, Medikamente (inkl. Verabreichungs-Log), Pflegeaufgaben | ✅ Fertig |
| [`app/routers/food.py`](../backend/app/routers/food.py) | 9 Endpoints: Rezepte (`recipe_router`) und Wochenmenü (`meal_plan_router`, inkl. „Fehlende Zutaten zur Einkaufsliste“) | ✅ Fertig |
| [`app/routers/notes.py`](../backend/app/routers/notes.py) | 4 Endpoints: Notizen (CRUD, angepinnt, Tag) | ✅ Fertig |
| [`app/routers/files.py`](../backend/app/routers/files.py) | 3 Endpoints: Upload (Bild-Resize, Magic-Byte-Prüfung, Speicher-Limit), geschützter Download, Löschen (mit `FILE_IN_USE`-Schutz) | ✅ Fertig |
| [`app/routers/documents.py`](../backend/app/routers/documents.py) | 10 Endpoints: Dokument-Ablage (mehrseitig, Kategorien, Ablaufdatum, Speicher-Auslastung) | ✅ Fertig |
| [`app/routers/push.py`](../backend/app/routers/push.py) | 4 Endpoints: Web-Push-Konfiguration, Geräte an-/abmelden, Test-Benachrichtigung | ✅ Fertig |
| [`app/routers/dashboard.py`](../backend/app/routers/dashboard.py) | 2 Endpoints: aggregierte Startseite (Aufgaben, Einkauf, Finanzen) und Zahl fürs App-Icon (`/badge`) | ✅ Fertig |
| [`app/services/balance_service.py`](../backend/app/services/balance_service.py) | Saldo-Berechnung (von Ausgaben-Router und Dashboard gemeinsam genutzt; gelöschte Ausgaben/Ausgleiche zählen nicht) | ✅ Fertig |
| [`app/services/finance_rules.py`](../backend/app/services/finance_rules.py) | Finanzregeln: Betrags-/Datumsgrenzen (≤ 10^9 Rappen, ±10 Jahre), Monatsvalidierung, `If-Match`, letzter Ausgleich je Personenpaar | ✅ Fertig |
| [`app/services/chore_scheduler.py`](../backend/app/services/chore_scheduler.py) | Lazy-Materialisierung, Kalender-basierte Rotation, Datumsberechnung (weekly/biweekly/monthly) | ✅ Fertig |
| [`app/services/locking.py`](../backend/app/services/locking.py) | Zeilensperren für Check-then-Act: `lock_household(db, id)`, `lock_row(db, Model, id)` (`SELECT … FOR UPDATE`, auf SQLite No-Op) | ✅ Fertig |
| [`app/services/client_ids.py`](../backend/app/services/client_ids.py) | Vom Client erzeugte IDs: idempotentes Anlegen (Offline-Meilenstein M0) | ✅ Fertig |
| [`app/services/event_times.py`](../backend/app/services/event_times.py) | Termin-Zeiten als Wanduhrzeit in der Haushalts-Zeitzone (Speicherung UTC) | ✅ Fertig |
| [`app/services/file_cleanup.py`](../backend/app/services/file_cleanup.py) | Periodisches Aufräumen verwaister Uploads | ✅ Fertig |
| [`app/services/household_checks.py`](../backend/app/services/household_checks.py) | Prüfungen auf Haushaltsmitgliedschaft (Teilnehmer, Ausgleichs-Parteien, Ex-Mitglieder) | ✅ Fertig |
| [`app/services/invite_code.py`](../backend/app/services/invite_code.py) | Eindeutige Invite-Code-Generierung mit Retry-Logik | ✅ Fertig |
| [`app/services/push_service.py`](../backend/app/services/push_service.py) | Web-Push-Versand (Endpoint-Allowlist) und Scheduler für Todo-Erinnerungen, Tier- und Pflanzenpflege, Putzplan („Du bist dran“, materialisiert die heutigen Ämtli selbst) und Ablaufdaten von Dokumenten (30 Tage vorher und am Tag); jede Payload trägt die Zahl fürs App-Icon | ✅ Fertig |
| [`app/services/attention.py`](../backend/app/services/attention.py) | Was heute ansteht (Zahl am App-Icon und Liste fürs Widget): bis heute fällige offene Aufgaben und Ämtli (eigene oder niemandem zugewiesene), Tier- und Pflanzenpflege | ✅ Fertig |
| [`app/routers/widget.py`](../backend/app/routers/widget.py) | Homescreen-Widget (Scriptable): Nur-Lese-Schlüssel verwalten (3 Endpoints) und Widget-Daten (`/api/widget/summary`) — siehe [`widget.md`](widget.md) | ✅ Fertig |
| [`app/services/storage.py`](../backend/app/services/storage.py) | `LocalStorageService`: Dateien unter `UPLOAD_DIR/{household_id}/` | ✅ Fertig |
| [`alembic.ini`](../backend/alembic.ini), `migrations/` | Alembic-Konfiguration und -Migrationen (33 Versionen unter `migrations/versions/`, einziger Kopf `w1x2y3z4a5b6`) | ✅ Fertig |
| [`scripts/regenerate_invite_codes.py`](../backend/scripts/regenerate_invite_codes.py) | Dry-Run/Apply-Script für Invite-Code-Migration | ✅ Fertig |
| [`scripts/generate_vapid_keys.py`](../backend/scripts/generate_vapid_keys.py) | Erzeugt VAPID-Schlüssel für Web Push | ✅ Fertig |
| [`pyproject.toml`](../backend/pyproject.toml) | ruff-Konfiguration (E, F, I, B) | ✅ Fertig |

### Backend-Tests (`backend/tests/`)

62 Testdateien, 837 Tests (SQLite in-memory, Coverage 94 %). Die Mehrmandanten-Dateien (`*_scoping`) prüfen jeweils, dass Zugriffe auf fremde Haushalte mit 403 abgewiesen werden.

| Datei | Abdeckung | Status |
|---|---|---|
| [`conftest.py`](../backend/tests/conftest.py) | SQLite in-memory DB (StaticPool), Multi-Tenant-Fixtures (2 Haushalte, 3 User), Socket-Mock | ✅ Fertig |
| [`pg/`](../backend/tests/pg/README.md) | PostgreSQL-Lane (Marker `pg`, nur mit `TEST_PG_URL`): frische DB per `alembic upgrade head`, echte Sessions pro Request, `run_parallel`, Emit-Recorder; Smoke/Drift-Check, Konflikt- und Migrationstests | ✅ Fertig |
| [`test_patch_null.py`](../backend/tests/test_patch_null.py) | `null` auf jedem NOT-NULL-Feld jedes PATCH-Endpunkts → 422, Zeile unverändert (CASA-04/37) | ✅ Fertig |
| [`test_db_conflicts.py`](../backend/tests/test_db_conflicts.py) | DB-Konflikt-Mapping → 409 `CONFLICT_RETRY`, Rollback in `get_db`, Sperr-Helfer | ✅ Fertig |
| **Auth und Sicherheit** | | |
| [`test_auth_guard.py`](../backend/tests/test_auth_guard.py) | Kein/ungültiger/abgelaufener Token → 401 | ✅ Fertig |
| [`test_auth_refresh.py`](../backend/tests/test_auth_refresh.py) | Refresh-Token-Rotation, Reuse-Erkennung, Logout | ✅ Fertig |
| [`test_register.py`](../backend/tests/test_register.py) | Registrierung mit Code, ohne Code, beides/keines → 422 | ✅ Fertig |
| [`test_admin_guard.py`](../backend/tests/test_admin_guard.py) | `verify_household_admin`: Admin ok, Nicht-Admin abgewiesen | ✅ Fertig |
| [`test_security_hardening.py`](../backend/tests/test_security_hardening.py) | HTTP-Header, CORS, Rate-Limits, JWT-Claims, Login-Timing | ✅ Fertig |
| [`test_rate_limit_proxy.py`](../backend/tests/test_rate_limit_proxy.py) | Rate-Limiter unterscheidet Clients per `X-Forwarded-For` | ✅ Fertig |
| [`test_startup_config.py`](../backend/tests/test_startup_config.py) | Startup-Validierung der Konfiguration | ✅ Fertig |
| [`test_upload_security.py`](../backend/tests/test_upload_security.py) | Regressionstests Upload-Review (`docs/security/epic8-upload-review.md`) | ✅ Fertig |
| **Haushalt** | | |
| [`test_household_join.py`](../backend/tests/test_household_join.py) | Beitritt: gültiger/ungültiger Code, bereits Mitglied, Groß-/Kleinschreibung | ✅ Fertig |
| [`test_households.py`](../backend/tests/test_households.py) | Erstellen, Umbenennen, Join-Event, Rollen in Mitgliederliste | ✅ Fertig |
| [`test_leave_remove.py`](../backend/tests/test_leave_remove.py) | Verlassen/Entfernen: Auto-Promotion, Cascade, Salden, 403-Regeln | ✅ Fertig |
| [`test_member_lifecycle.py`](../backend/tests/test_member_lifecycle.py) | Entfernte Mitglieder verlassen den Echtzeit-Raum, Einladungscode-Erneuerung | ✅ Fertig |
| [`test_currency.py`](../backend/tests/test_currency.py) | Währungs-Mismatch, Default-Währung, `/me`-Antwort | ✅ Fertig |
| [`test_db_integrity.py`](../backend/tests/test_db_integrity.py) | Löschregeln, eindeutige Stimmen und Buchungen | ✅ Fertig |
| [`test_pool_contention.py`](../backend/tests/test_pool_contention.py) | Regressionstest Connection-Pool und Event-Loop-Blocking | ✅ Fertig |
| **Einkauf und Aufgaben** | | |
| [`test_shopping_scoping.py`](../backend/tests/test_shopping_scoping.py) | Einkaufseinträge und -listen: eigene lesen, Cross-Household → 403 | ✅ Fertig |
| [`test_shopping_stores.py`](../backend/tests/test_shopping_stores.py) | Geschäfts-Verwaltung: Distinct, Umbenennen, Auflösen, Normalisierung (Groß-/Kleinschreibung), Cross-Tenant | ✅ Fertig |
| [`test_todo_scoping.py`](../backend/tests/test_todo_scoping.py) | Todos: Mehrmandanten-Scoping | ✅ Fertig |
| [`test_todo_tags.py`](../backend/tests/test_todo_tags.py) | Todo-Tags (JSON-Feld) | ✅ Fertig |
| [`test_todo_claim.py`](../backend/tests/test_todo_claim.py) | `POST /todos/{id}/claim` | ✅ Fertig |
| [`test_todo_reminders.py`](../backend/tests/test_todo_reminders.py) | Erinnerungen: CRUD, Scoping, Maximum 5 | ✅ Fertig |
| [`test_chores.py`](../backend/tests/test_chores.py) | Scheduler-Unit-Tests, API-Tests, Socket-Events | ✅ Fertig |
| [`test_chore_scoping.py`](../backend/tests/test_chore_scoping.py) | Cross-Household 403 auf alle Chore-Endpoints | ✅ Fertig |
| **Finanzen** | | |
| [`test_expense_scoping.py`](../backend/tests/test_expense_scoping.py) | Ausgaben: Mehrmandanten-Scoping inkl. Balances | ✅ Fertig |
| [`test_expense_splits.py`](../backend/tests/test_expense_splits.py) | `split_evenly`, Even/Custom-Split-API, Validierung (422), Reshare, DELETE | ✅ Fertig |
| [`test_expense_balances.py`](../backend/tests/test_expense_balances.py) | `compute_settlements` und Balances-Endpoint | ✅ Fertig |
| [`test_expense_events.py`](../backend/tests/test_expense_events.py) | Socket.IO-Events bei Ausgaben, Room-Check | ✅ Fertig |
| [`test_settlements.py`](../backend/tests/test_settlements.py) | Ausgleichszahlungen: Scoping, CRUD, Validierung, Salden, Events | ✅ Fertig |
| [`test_finance_correctness.py`](../backend/tests/test_finance_correctness.py) | Datenkorrektheit: doppelte Teilnehmer, Ex-Mitglieder, Standard-Zahler | ✅ Fertig |
| [`test_finance_summary.py`](../backend/tests/test_finance_summary.py) | `GET /finance-summary` | ✅ Fertig |
| [`test_budget_scoping.py`](../backend/tests/test_budget_scoping.py) | Budget: Mehrmandanten-Scoping | ✅ Fertig |
| [`test_recurring_bill_scoping.py`](../backend/tests/test_recurring_bill_scoping.py) | Wiederkehrende Rechnungen: Mehrmandanten-Scoping | ✅ Fertig |
| [`test_recurring_bill_book.py`](../backend/tests/test_recurring_bill_book.py) | Idempotenz von `POST /recurring-bills/{id}/book` | ✅ Fertig |
| [`test_finance_integrity.py`](../backend/tests/test_finance_integrity.py) | Version/If-Match, Soft Delete + Verlauf, Restore (inkl. Rechnungsbuchung, Ex-Mitglied), Settlement-Idempotenz/Plausibilität, Grenzen, Paginierung, Nachbuchen | ✅ Fertig |
| [`test_finance_props.py`](../backend/tests/test_finance_props.py) | Property-based (hypothesis): Aufteilung, Ausgleichsvorschläge, Custom-Shares | ✅ Fertig |
| [`pg/test_pg_finance.py`](../backend/tests/pg/test_pg_finance.py), [`pg/test_pg_finance_props.py`](../backend/tests/pg/test_pg_finance_props.py) | PostgreSQL: parallele Ausgaben-Änderungen, Settlement-Duplikate, Restore ‖ Neubuchung, Migration `fin1a2b3c4d5`; Ledger-Invarianten über zufällige REST-Folgen | ✅ Fertig |
| [`test_dashboard_scoping.py`](../backend/tests/test_dashboard_scoping.py) | Dashboard: Mehrmandanten-Scoping | ✅ Fertig |
| **Kalender, Haustiere, Essen, Notizen** | | |
| [`test_calendar_scoping.py`](../backend/tests/test_calendar_scoping.py) | Kalender: Mehrmandanten-Scoping | ✅ Fertig |
| [`test_event_scoping.py`](../backend/tests/test_event_scoping.py) | Termine: Mehrmandanten-Scoping | ✅ Fertig |
| [`test_event_times.py`](../backend/tests/test_event_times.py) | Termin-Zeiten in Haushaltszeit, Zeitraum-Abfragen | ✅ Fertig |
| [`test_poll_scoping.py`](../backend/tests/test_poll_scoping.py) | Abstimmungen: Mehrmandanten-Scoping | ✅ Fertig |
| [`test_meal_poll.py`](../backend/tests/test_meal_poll.py) | Essens-Abstimmungen (`poll_type='meal'`) | ✅ Fertig |
| [`test_pet_scoping.py`](../backend/tests/test_pet_scoping.py) | Haustiere: Mehrmandanten-Scoping | ✅ Fertig |
| [`test_feeding_scoping.py`](../backend/tests/test_feeding_scoping.py) | Fütterungs-Log: Mehrmandanten-Scoping | ✅ Fertig |
| [`test_medication_scoping.py`](../backend/tests/test_medication_scoping.py) | Medikamente: Mehrmandanten-Scoping | ✅ Fertig |
| [`test_pet_care_scoping.py`](../backend/tests/test_pet_care_scoping.py) | Pflegeaufgaben: Mehrmandanten-Scoping | ✅ Fertig |
| [`test_food_scoping.py`](../backend/tests/test_food_scoping.py) | Rezepte und Wochenmenü: Mehrmandanten-Scoping | ✅ Fertig |
| [`test_food_shopping.py`](../backend/tests/test_food_shopping.py) | „Fehlende Zutaten zur Einkaufsliste“ | ✅ Fertig |
| [`test_note_scoping.py`](../backend/tests/test_note_scoping.py) | Notizen: Mehrmandanten-Scoping | ✅ Fertig |
| **Dateien, Dokumente, Push, Sync** | | |
| [`test_files_scoping.py`](../backend/tests/test_files_scoping.py) | Upload-Infrastruktur: Cross-Tenant, Validierung, Upload/Download/Delete | ✅ Fertig |
| [`test_file_references.py`](../backend/tests/test_file_references.py) | Datei-Referenzen zwischen Haustieren und Dokumenten, Aufräumen | ✅ Fertig |
| [`test_documents.py`](../backend/tests/test_documents.py) | Dokument-Ablage: CRUD, mehrseitig, Speicher-Limit, Scoping | ✅ Fertig |
| [`test_push.py`](../backend/tests/test_push.py) | Web Push: Subscription-API (SSRF-Allowlist), Scheduler | ✅ Fertig |
| [`test_push_chores_documents.py`](../backend/tests/test_push_chores_documents.py) | Web Push für Putzplan und Dokument-Ablauf, Badge-Zahl (Service und Endpoint) | ✅ Fertig |
| [`test_offline_sync.py`](../backend/tests/test_offline_sync.py) | Offline-Meilenstein M0: Client-IDs, `version`/`updated_at` | ✅ Fertig |

### Betrieb und CI (Repository-Wurzel)

| Datei | Zweck | Status |
|---|---|---|
| [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | GitHub Actions: Jobs `backend` (ruff, pytest mit Coverage), `backend-postgres` (postgres:16, `alembic upgrade head`, `pytest -m pg`, `alembic downgrade -1 && upgrade head`, Restore-Drill `scripts/restore-drill.sh`), `frontend` (Locale-Check, Typecheck, Vitest mit Coverage), `dependency-audit` (pip-audit, npm audit) | ✅ Fertig |
| [`docker-compose.yml`](../docker-compose.yml) | Entwicklungs-Setup (Datenbank, Backend, Frontend; Ports nur lokal gebunden) | ✅ Fertig |
| [`docker-compose.prod.yml`](../docker-compose.prod.yml) | Produktion hinter Nginx Proxy Manager (Healthchecks für alle drei Container, keine veröffentlichten Ports, Log-Rotation `json-file` 5×10 MB, vertrauenswürdige Proxy-Bereiche `TRUSTED_PROXY_CIDRS`/`FORWARDED_ALLOW_IPS`) | ✅ Fertig |
| [`.env.example`](../.env.example), [`.env.prod.example`](../.env.prod.example) | Vorlagen für Umgebungsvariablen | ✅ Fertig |
| [`backend/Dockerfile`](../backend/Dockerfile), [`frontend/Dockerfile`](../frontend/Dockerfile), [`frontend/nginx.conf`](../frontend/nginx.conf), [`frontend/nginx/security-headers.conf`](../frontend/nginx/security-headers.conf) | Container-Images, Nginx-Konfiguration und Security-Header fürs Frontend | ✅ Fertig |
| [`scripts/backup-db.ps1`](../scripts/backup-db.ps1), [`scripts/restore-db.ps1`](../scripts/restore-db.ps1) | Backup/Restore von Datenbank und Uploads (PowerShell). Backup: Dump vor Uploads, `-Consistent` (Backend gestoppt), `-Keep`, `-CopyTo` (Off-Host). Restore: Backend stoppen, Dump in frische DB (`--single-transaction --exit-on-error`), Tausch, Uploads, Backend starten + Health-Check (CASA-07, CASA-57) | ✅ Fertig |
| [`scripts/restore-db.sh`](../scripts/restore-db.sh), [`scripts/restore-drill.sh`](../scripts/restore-drill.sh) | Restore für Linux-Hosts (gleiche Logik, auch direkt gegen eine DB-URL) und Restore-Drill für CI/Betrieb | ✅ Fertig |

### Frontend (`frontend/src/`)

| Datei | Zweck | Status |
|---|---|---|
| [`App.vue`](../frontend/src/App.vue) | App-Shell: Desktop-Top-Bar (6 Links), Mobile-Bottom-Nav (4 Tabs + „Mehr“), Offline-Banner, Sync-Status, Toasts; Echtzeit-Sitzung über `composables/useRealtimeSession.ts` | ✅ Fertig |
| [`main.ts`](../frontend/src/main.ts) | App-Bootstrap, Pinia, Router, i18n, Theme-CSS-Import, PWA-Registrierung | ✅ Fertig |
| [`pwa.ts`](../frontend/src/pwa.ts) | Service-Worker-Registrierung, Toast + dauerhafter Eintrag „Update verfügbar“ im Mehr-Sheet, Update-Prüfung bei Rückkehr in die App und stündlich (`composables/usePwaUpdate.ts`, CASA-41) | ✅ Fertig |
| [`i18n.ts`](../frontend/src/i18n.ts) | vue-i18n-Setup, detectLocale (localStorage → navigator.language → en) | ✅ Fertig |
| [`env.d.ts`](../frontend/src/env.d.ts) | Typen für Vite-Umgebungsvariablen | ✅ Fertig |
| [`api/client.ts`](../frontend/src/api/client.ts) | Axios-Client (`API_BASE`) mit JWT-Interceptor und 401 → Refresh → Retry | ✅ Fertig |
| [`types/index.ts`](../frontend/src/types/index.ts) | TypeScript-Typen aller Module (Haushalt, Einkauf, Aufgaben, Finanzen, Kalender, Haustiere, Essen, Notizen, Dokumente) | ✅ Fertig |
| **Services** | | |
| [`services/tokenStorage.ts`](../frontend/src/services/tokenStorage.ts) | Token-Persistenz (localStorage hinter `TokenStorage`-Interface) | ✅ Fertig |
| [`services/pushService.ts`](../frontend/src/services/pushService.ts) | Web-Push-Abo im Browser verwalten und mit dem Backend synchronisieren | ✅ Fertig |
| [`public/push-sw.js`](../frontend/public/push-sw.js) | Service-Worker-Teil für Push-Benachrichtigungen; Icon-Zahl nur für den Haushalt, den die App gerade zeigt (CASA-40) | ✅ Fertig |
| **i18n** | | |
| [`locales/de.json`](../frontend/src/locales/de.json) | Deutsche Übersetzungen (1173 Keys) | ✅ Fertig |
| [`locales/en.json`](../frontend/src/locales/en.json) | Englische Übersetzungen (1173 Keys) | ✅ Fertig |
| [`scripts/check-locales.js`](../frontend/scripts/check-locales.js) | Build-Script: prüft Key-Sync zwischen DE und EN | ✅ Fertig |
| **Design-System** | | |
| [`assets/theme.css`](../frontend/src/assets/theme.css) | Design-Token-System: Farben (Light/Dark), Typografie (Nunito/Quicksand), Spacing, Radii, Schatten, Transitions, Avatar-Palette, Global Reset | ✅ Fertig |
| [`components/ui/BaseButton.vue`](../frontend/src/components/ui/BaseButton.vue) | Button: Varianten, 2 Grössen, Loading-State | ✅ Fertig |
| [`components/ui/BaseInput.vue`](../frontend/src/components/ui/BaseInput.vue) | Input: Label, Error-State, v-model, iOS-Zoom-Prevention (16px) | ✅ Fertig |
| [`components/ui/BaseCard.vue`](../frontend/src/components/ui/BaseCard.vue) | Card: 3 Padding-Stufen | ✅ Fertig |
| [`components/ui/BaseCheckCircle.vue`](../frontend/src/components/ui/BaseCheckCircle.vue) | Runde Checkbox | ✅ Fertig |
| [`components/ui/BasePillTabs.vue`](../frontend/src/components/ui/BasePillTabs.vue) | Generische Pill-Filterleiste | ✅ Fertig |
| [`components/ui/BaseEmptyState.vue`](../frontend/src/components/ui/BaseEmptyState.vue) | Empty-State mit Icon, Titel, Untertitel, Action-Slot | ✅ Fertig |
| [`components/ui/BaseDialog.vue`](../frontend/src/components/ui/BaseDialog.vue) | Dialog (Teleport, Overlay, Esc, Transitions) | ✅ Fertig |
| [`components/ui/BaseSkeleton.vue`](../frontend/src/components/ui/BaseSkeleton.vue) | Skeleton-Loading-Platzhalter | ✅ Fertig |
| [`components/ui/BaseSpinner.vue`](../frontend/src/components/ui/BaseSpinner.vue) | CSS-only Spinner, 2 Grössen | ✅ Fertig |
| [`components/ui/BaseAvatar.vue`](../frontend/src/components/ui/BaseAvatar.vue) | Avatar mit deterministischer Farbe pro User | ✅ Fertig |
| [`components/ui/PageHeader.vue`](../frontend/src/components/ui/PageHeader.vue) | Einheitliche Seitenkopfzeile | ✅ Fertig |
| **Stores** | | |
| [`stores/auth.ts`](../frontend/src/stores/auth.ts) | Login, Register (+ Invite-Code), Token-Persistenz und -Refresh, fetchMe, Haushalt-Wechsel, Socket-Handler (`household_*`) | ✅ Fertig |
| [`stores/shopping.ts`](../frontend/src/stores/shopping.ts) | Einkauf: Listen und Einträge, Optimistic Updates, Race-Condition-Schutz, Geschäfts-Verwaltung | ✅ Fertig |
| [`stores/todos.ts`](../frontend/src/stores/todos.ts) | Todos: CRUD, Claim, Erinnerungen, Optimistic Updates | ✅ Fertig |
| [`stores/chores.ts`](../frontend/src/stores/chores.ts) | Ämtli: CRUD, Optimistic Updates, Toggle-Mutex, Socket-Handler | ✅ Fertig |
| [`stores/expenses.ts`](../frontend/src/stores/expenses.ts) | Ausgaben: CRUD mit Version (If-Match, Konflikt übernimmt Server-Stand), Wiederherstellen, Verlauf, „Mehr laden“, Socket-Handler, debounced Balances-Refetch | ✅ Fertig |
| [`stores/settlements.ts`](../frontend/src/stores/settlements.ts) | Ausgleichszahlungen: CRUD mit Client-ID, Plausibilitätsprüfung, Wiederherstellen, Verlauf, „Mehr laden“, Socket-Handler | ✅ Fertig |
| [`stores/finance.ts`](../frontend/src/stores/finance.ts) | Budget, wiederkehrende Rechnungen (inkl. pausierter, Nachbuchen), Finanz-Zusammenfassung; Budget-Events nur für den angezeigten Monat | ✅ Fertig |
| [`stores/dashboard.ts`](../frontend/src/stores/dashboard.ts) | Dashboard-Daten (mit Invalidierung) | ✅ Fertig |
| [`stores/calendar.ts`](../frontend/src/stores/calendar.ts) | Kalender und Termine | ✅ Fertig |
| [`stores/polls.ts`](../frontend/src/stores/polls.ts) | Abstimmungen | ✅ Fertig |
| [`stores/pets.ts`](../frontend/src/stores/pets.ts) | Haustiere, Fütterung, Medikamente, Pflegeaufgaben | ✅ Fertig |
| [`stores/food.ts`](../frontend/src/stores/food.ts) | Rezepte und Wochenmenü | ✅ Fertig |
| [`stores/notes.ts`](../frontend/src/stores/notes.ts) | Notizen | ✅ Fertig |
| [`stores/documents.ts`](../frontend/src/stores/documents.ts) | Dokument-Ablage: Liste mit Suche/Paginierung, Mehrseiten-Verwaltung, Speicher-Auslastung | ✅ Fertig |
| **Repositories** (Offline-Ready Seam, aktuell nur Online-Variante) | | |
| [`repositories/shoppingRepository.ts`](../frontend/src/repositories/shoppingRepository.ts) | Einkaufslisten, Einträge, Geschäfte | ✅ Fertig |
| [`repositories/todosRepository.ts`](../frontend/src/repositories/todosRepository.ts) | Todos und Erinnerungen | ✅ Fertig |
| [`repositories/householdsRepository.ts`](../frontend/src/repositories/householdsRepository.ts) | Beitreten, Einladungscode, Mitglieder, Erstellen, Umbenennen, Verlassen, Entfernen | ✅ Fertig |
| [`repositories/expensesRepository.ts`](../frontend/src/repositories/expensesRepository.ts) | Ausgaben (CRUD + Balances) | ✅ Fertig |
| [`repositories/settlementsRepository.ts`](../frontend/src/repositories/settlementsRepository.ts) | Ausgleichszahlungen | ✅ Fertig |
| [`repositories/choresRepository.ts`](../frontend/src/repositories/choresRepository.ts) | Ämtli und Zuweisungen | ✅ Fertig |
| [`repositories/financeRepository.ts`](../frontend/src/repositories/financeRepository.ts) | Budget, wiederkehrende Rechnungen, Finanz-Zusammenfassung | ✅ Fertig |
| [`repositories/dashboardRepository.ts`](../frontend/src/repositories/dashboardRepository.ts) | Dashboard | ✅ Fertig |
| [`repositories/calendarRepository.ts`](../frontend/src/repositories/calendarRepository.ts) | Kalender und Termine | ✅ Fertig |
| [`repositories/pollsRepository.ts`](../frontend/src/repositories/pollsRepository.ts) | Abstimmungen | ✅ Fertig |
| [`repositories/petsRepository.ts`](../frontend/src/repositories/petsRepository.ts) | Haustiere, Fütterung, Medikamente, Pflegeaufgaben | ✅ Fertig |
| [`repositories/foodRepository.ts`](../frontend/src/repositories/foodRepository.ts) | Rezepte und Wochenmenü | ✅ Fertig |
| [`repositories/notesRepository.ts`](../frontend/src/repositories/notesRepository.ts) | Notizen | ✅ Fertig |
| [`repositories/filesRepository.ts`](../frontend/src/repositories/filesRepository.ts) | Datei-Upload, geschützter Download, Löschen | ✅ Fertig |
| [`repositories/documentsRepository.ts`](../frontend/src/repositories/documentsRepository.ts) | Dokumente und Seiten | ✅ Fertig |
| [`repositories/pushRepository.ts`](../frontend/src/repositories/pushRepository.ts) | Web-Push-Konfiguration und -Abos | ✅ Fertig |
| **Utils** | | |
| [`utils/money.ts`](../frontend/src/utils/money.ts) | formatRappen (Intl.NumberFormat), parseAmountToRappen (String-basiert, kein Float) | ✅ Fertig |
| [`utils/apiErrors.ts`](../frontend/src/utils/apiErrors.ts) | Error-Code-Extraktion, i18n-Mapping für maschinenlesbare Backend-Codes | ✅ Fertig |
| [`utils/memberColor.ts`](../frontend/src/utils/memberColor.ts) | Deterministisches User→Farbe-Mapping | ✅ Fertig |
| [`utils/dates.ts`](../frontend/src/utils/dates.ts) | Datums-Helfer (z. B. `formatDateShort`) | ✅ Fertig |
| [`utils/storeName.ts`](../frontend/src/utils/storeName.ts) | Geschäftsnamen normalisieren und ohne Beachtung der Schreibweise vergleichen | ✅ Fertig |
| [`utils/syncVersion.ts`](../frontend/src/utils/syncVersion.ts) | Erkennung veralteter Events anhand von `version` | ✅ Fertig |
| [`utils/documents.ts`](../frontend/src/utils/documents.ts) | Ablaufstatus von Dokumenten (abgelaufen / läuft bald ab) | ✅ Fertig |
| [`utils/categoryColors.ts`](../frontend/src/utils/categoryColors.ts) | Standard-Farbpalette für neue Kalender | ✅ Fertig |
| **Composables** | | |
| [`composables/useSocket.ts`](../frontend/src/composables/useSocket.ts) | Socket.IO Client-Wrapper, Token-Übergabe nach Refresh (`reauth`), Reconnect nach serverseitigem Sitzungsende, Room-Status mit Retry bei `error` (CASA-46), Filter für Payloads fremder Haushalte | ✅ Fertig |
| [`composables/useRealtimeSession.ts`](../frontend/src/composables/useRealtimeSession.ts) | Echtzeit-Sitzung des App-Rahmens: Room des aktuellen Haushalts, Listener der Kern-Stores, Nachladen nur bei Anmeldung/Haushaltswechsel/Reconnect (CASA-44) | ✅ Fertig |
| [`utils/householdGuard.ts`](../frontend/src/utils/householdGuard.ts) | Haushalts-/Sitzungs-Generation: Store-Fetches verwerfen Antworten nach Haushaltswechsel oder Logout (CASA-12) | ✅ Fertig |
| [`composables/useConnectivity.ts`](../frontend/src/composables/useConnectivity.ts) | Online/Offline-Erkennung (navigator.onLine) | ✅ Fertig |
| [`composables/useToast.ts`](../frontend/src/composables/useToast.ts) | App-weites Toast-System | ✅ Fertig |
| [`composables/useTheme.ts`](../frontend/src/composables/useTheme.ts) | Theme-Einstellung (hell/dunkel/System), gespeichert in localStorage | ✅ Fertig |
| [`composables/useProtectedImage.ts`](../frontend/src/composables/useProtectedImage.ts) | JWT-geschützte Bilder als Blob-URL laden | ✅ Fertig |
| [`composables/usePhotoUpload.ts`](../frontend/src/composables/usePhotoUpload.ts) | Foto-Upload und Zuordnung an den ursprünglichen Haushalt und das Tier/die Pflanze binden; nicht zugeordnete Dateien aufräumen | ✅ Fertig |
| **Views** | | |
| [`views/LoginView.vue`](../frontend/src/views/LoginView.vue) | Login-Formular | ✅ Fertig |
| [`views/RegisterView.vue`](../frontend/src/views/RegisterView.vue) | Registrierung: Tab-Umschalter (Haushalt gründen / Mit Code beitreten), `?code=`-Query-Param | ✅ Fertig |
| [`views/NoHouseholdView.vue`](../frontend/src/views/NoHouseholdView.vue) | Kein-Haushalt-Zustand: Gründen / Beitreten | ✅ Fertig |
| [`views/DashboardView.vue`](../frontend/src/views/DashboardView.vue) | Startseite: Tagesgruss, Schnellzugriffe, Widgets | ✅ Fertig |
| [`views/CalendarView.vue`](../frontend/src/views/CalendarView.vue) | Kalender: Monats-, Wochen- und Listenansicht, Termine, Kalender-Verwaltung, Abstimmungen | ✅ Fertig |
| [`views/ShoppingView.vue`](../frontend/src/views/ShoppingView.vue) | Einkauf: Listen-Tabs, Einträge nach Geschäft | ✅ Fertig |
| [`views/TodosView.vue`](../frontend/src/views/TodosView.vue) | Aufgaben: vereinte Zeitleiste (Überfällig / Heute / Diese Woche / Später), Link zu „Ämtli verwalten“ | ✅ Fertig |
| [`views/ChoresView.vue`](../frontend/src/views/ChoresView.vue) | Putzplan: „Diese Woche“ + „Ämtli verwalten“, Filter Alle/Meine (Route `/chores`, nicht in der Top-Bar) | ✅ Fertig |
| [`views/ExpensesView.vue`](../frontend/src/views/ExpensesView.vue) | Finanzen: Budget, offene Rechnungen (Buchen mit Zahler- und Monatswahl), Rechnungsverwaltung, Ausgaben, Salden, Zahlungen, Verlauf gelöschter Einträge | ✅ Fertig |
| [`components/RecurringBillsManager.vue`](../frontend/src/components/RecurringBillsManager.vue) | Wiederkehrende Rechnungen anlegen, bearbeiten, pausieren, löschen; Standard-Zahler | ✅ Fertig |
| [`components/FinanceHistory.vue`](../frontend/src/components/FinanceHistory.vue) | Verlauf: gelöschte Ausgaben/Zahlungen („gelöscht von X am …“) und Wiederherstellen | ✅ Fertig |
| [`views/PetsView.vue`](../frontend/src/views/PetsView.vue) | Haustiere: Übersicht mit Fütterungs-Widget | ✅ Fertig |
| [`views/PetDetailView.vue`](../frontend/src/views/PetDetailView.vue) | Tierprofil: Stammdaten, Foto, Medikamente, Gesundheitseinträge, Pflegeaufgaben | ✅ Fertig |
| [`views/FoodView.vue`](../frontend/src/views/FoodView.vue) | Essen: Wochenmenü, Rezepte, Essens-Abstimmungen | ✅ Fertig |
| [`views/NotesView.vue`](../frontend/src/views/NotesView.vue) | Notizen: Pinnen, Tag-Filter | ✅ Fertig |
| [`views/DocumentsView.vue`](../frontend/src/views/DocumentsView.vue) | Dokument-Ablage: Suche, Kategorien, Mehrseiten-Upload, Vorschau, Ablaufstatus | ✅ Fertig |
| [`views/HouseholdView.vue`](../frontend/src/views/HouseholdView.vue) | Haushalt-Verwaltung: Mitglieder, Einladen (Code erneuern), Verlassen/Entfernen, App-Einstellungen inkl. Push | ✅ Fertig |
| **Komponenten** | | |
| [`components/TheBottomNav.vue`](../frontend/src/components/TheBottomNav.vue) | Mobile Bottom-Nav: Start, Kalender, Aufgaben, Einkauf, „Mehr“ | ✅ Fertig |
| [`components/MoreSheet.vue`](../frontend/src/components/MoreSheet.vue) | „Mehr“-Sheet: Finanzen, Katzen, Essen, Notizen, Dokumente, Einstellungen | ✅ Fertig |
| [`components/ConnectionStatus.vue`](../frontend/src/components/ConnectionStatus.vue) | Verbindungsstatus mit Text und Erklärung in „Mehr“ und Einstellungen; Offline hat Vorrang | ✅ Fertig |
| [`components/ShoppingList.vue`](../frontend/src/components/ShoppingList.vue) | Einkaufsliste: Geschäfts-Chips, Gruppierung, Quick-Add, Kebab-Menü (Umbenennen/Auflösen) | ✅ Fertig |
| [`components/ShoppingItemEditSheet.vue`](../frontend/src/components/ShoppingItemEditSheet.vue) | Eintrag bearbeiten: Name, Menge, Geschäft, Abteilung | ✅ Fertig |
| [`components/TodoList.vue`](../frontend/src/components/TodoList.vue) | Aufgabenliste: Quick-Add, Detail-Edit, Zuweisung, Fälligkeit, Erinnerungen | ✅ Fertig |
| [`components/ExpenseList.vue`](../frontend/src/components/ExpenseList.vue) | Ausgabenliste: Bearbeiten, Optimistic Delete | ✅ Fertig |
| [`components/ExpenseFormDialog.vue`](../frontend/src/components/ExpenseFormDialog.vue) | Ausgabe-Dialog: Erstellen/Bearbeiten, Even/Custom-Split | ✅ Fertig |
| [`components/BalanceSummary.vue`](../frontend/src/components/BalanceSummary.vue) | Saldo-Übersicht, Ausgleichsvorschläge, Inline-Erfassung von Ausgleichszahlungen | ✅ Fertig |
| [`components/CalendarMonthGrid.vue`](../frontend/src/components/CalendarMonthGrid.vue) | Monatsraster des Kalenders mit Tagesdetails | ✅ Fertig |
| [`components/PetPhotoAvatar.vue`](../frontend/src/components/PetPhotoAvatar.vue) | Tierfoto (sm/md/lg) mit geschütztem Bild-Download | ✅ Fertig |
| [`components/PushSettings.vue`](../frontend/src/components/PushSettings.vue) | Web-Push ein-/ausschalten und testen | ✅ Fertig |
| **Router** | | |
| [`router/index.ts`](../frontend/src/router/index.ts) | Routen: `/dashboard`, `/calendar`, `/shopping`, `/todos`, `/expenses`, `/chores`, `/pets`, `/pets/:id`, `/food`, `/notes`, `/documents`, `/household`, `/login`, `/register`, `/no-household`; `/` leitet auf `/dashboard`; Auth-Guard (+ 0-Haushalte-Guard) | ✅ Fertig |

### Frontend-Tests (`frontend/src/**/__tests__/`)

33 Testdateien, 473 Tests (Vitest, Umgebung `node`). Die Coverage (77,49 % Statements, 72,14 % Branches) misst nur `utils/`, `stores/` und `repositories/`. Views und Komponenten sind nicht Teil dieser Coverage; lokale Browserprüfungen stehen im [aktuellen Audit](qa/current-audit-fixes.md).

| Datei | Abdeckung | Status |
|---|---|---|
| [`test/setup.ts`](../frontend/src/test/setup.ts) | Vitest-Setup | ✅ Fertig |
| [`stores/__tests__/helpers.ts`](../frontend/src/stores/__tests__/helpers.ts) | Test-Hilfen für die Store-Tests | ✅ Fertig |
| [`stores/__tests__/auth.test.ts`](../frontend/src/stores/__tests__/auth.test.ts) | Auth-Store: Initialisierung, Refresh, Haushalte, Logout | ✅ Fertig |
| [`stores/__tests__/shopping.test.ts`](../frontend/src/stores/__tests__/shopping.test.ts) | Einkauf-Store: Optimistic Updates, Rollback, Geschäfts-Verwaltung | ✅ Fertig |
| [`stores/__tests__/todos.test.ts`](../frontend/src/stores/__tests__/todos.test.ts) | Todos-Store | ✅ Fertig |
| [`stores/__tests__/chores.test.ts`](../frontend/src/stores/__tests__/chores.test.ts) | Chores-Store: Toggle-Mutex, Rollback beim Löschen | ✅ Fertig |
| [`stores/__tests__/expenses.test.ts`](../frontend/src/stores/__tests__/expenses.test.ts) | Expenses-Store | ✅ Fertig |
| [`stores/__tests__/syncRaces.test.ts`](../frontend/src/stores/__tests__/syncRaces.test.ts) | Race-Conditions zwischen REST-Antworten und Socket-Events (versionierte Merges) | ✅ Fertig |
| [`utils/__tests__/money.test.ts`](../frontend/src/utils/__tests__/money.test.ts) | `formatRappen`, `parseAmountToRappen` | ✅ Fertig |
| [`utils/__tests__/apiErrors.test.ts`](../frontend/src/utils/__tests__/apiErrors.test.ts) | Error-Code-Extraktion | ✅ Fertig |
| [`utils/__tests__/dates.test.ts`](../frontend/src/utils/__tests__/dates.test.ts) | Datums-Helfer | ✅ Fertig |
| [`utils/__tests__/documents.test.ts`](../frontend/src/utils/__tests__/documents.test.ts) | Ablaufstatus von Dokumenten | ✅ Fertig |
| [`utils/__tests__/memberColor.test.ts`](../frontend/src/utils/__tests__/memberColor.test.ts) | User→Farbe-Mapping | ✅ Fertig |
| [`utils/__tests__/storeName.test.ts`](../frontend/src/utils/__tests__/storeName.test.ts) | Geschäftsnamen-Normalisierung | ✅ Fertig |
| [`utils/__tests__/syncVersion.test.ts`](../frontend/src/utils/__tests__/syncVersion.test.ts) | Erkennung veralteter Versionen | ✅ Fertig |

---

## 4. API-Endpoints

124 Endpoints (123 in den Routern plus Health-Check). Maßgeblich ist die OpenAPI-Doku des Backends unter `/docs`. Alle Pfade stehen ohne Weiterleitung bei fehlendem oder überzähligem Slash (`redirect_slashes=False`): Der abschliessende Slash muss exakt so verwendet werden, wie er hier steht. `{id}` steht für die Haushalts-ID; alle Endpoints unter `/api/households/{id}/…` prüfen die Mitgliedschaft (fremder Haushalt → 403). Rate-Limits gelten pro IP und im Speicher; bei Überschreitung antwortet der Server mit 429.

| Method | Path | Auth | Beschreibung |
|---|---|---|---|
| **Auth** | | | |
| POST | `/api/auth/register` | ❌ | Registrieren: `household_name` ODER `invite_code`; Rate-Limit 3/Stunde |
| POST | `/api/auth/login` | ❌ | Login (Formular-Daten), gibt Access- und Refresh-Token zurück; Rate-Limit 5/Minute |
| POST | `/api/auth/refresh` | ❌ | Refresh-Token-Rotation mit Reuse-Erkennung; Rate-Limit 30/Minute |
| POST | `/api/auth/logout` | ❌ | Refresh-Token widerrufen (idempotent, 204); Rate-Limit 30/Minute |
| GET | `/api/auth/me` | ✅ | User-Info + Haushalte (inkl. Rolle, Währung) |
| **Haushalt** | | | |
| POST | `/api/households/` | ✅ | Haushalt erstellen (Ersteller wird Admin) |
| POST | `/api/households/join` | ✅ | Haushalt per Einladungscode beitreten; Rate-Limit 5/Minute und 20/Stunde |
| PATCH | `/api/households/{id}` | ✅ Admin | Haushalt umbenennen |
| GET | `/api/households/{id}/members` | ✅ | Mitglieder-Liste (inkl. Rolle) |
| GET | `/api/households/{id}/invite-code` | ✅ | Einladungscode des Haushalts |
| POST | `/api/households/{id}/invite-code/rotate` | ✅ Admin | Neuen Einladungscode erzeugen (alter wird ungültig) |
| POST | `/api/households/{id}/leave` | ✅ | Haushalt verlassen (204) |
| DELETE | `/api/households/{id}/members/{user_id}` | ✅ Admin | Mitglied entfernen (204) |
| GET | `/api/households/{id}/finance-summary` | ✅ | Finanz-Zusammenfassung eines Monats (`month`, Default aktueller Monat) |
| **Dashboard und Aufgaben** | | | |
| GET | `/api/households/{id}/dashboard` | ✅ | Aggregierte Startseite (Aufgaben, Ämtli heute + überfällig wie die Badge-Zahl, Einkauf, Finanzen) |
| GET | `/api/households/{id}/dashboard/badge` | ✅ | Zahl am App-Icon für die aufrufende Person (`{count}`) |
| GET/POST/DELETE | `/api/households/{id}/widget-token` | ✅ | Nur-Lese-Schlüssel fürs Homescreen-Widget anzeigen/erzeugen/widerrufen |
| GET | `/api/widget/summary` | Widget-Schlüssel | Widget-Daten (fällig heute, Einkauf, Termine) — [`widget.md`](widget.md) |
| **Einkauf** | | | |
| GET | `/api/households/{id}/shopping-lists/` | ✅ | Einkaufslisten |
| POST | `/api/households/{id}/shopping-lists/` | ✅ | Liste erstellen |
| PATCH | `/api/households/{id}/shopping-lists/{list_id}` | ✅ | Liste aktualisieren |
| DELETE | `/api/households/{id}/shopping-lists/{list_id}` | ✅ | Liste löschen |
| GET | `/api/households/{id}/shopping-items/` | ✅ | Einkaufseinträge |
| POST | `/api/households/{id}/shopping-items/` | ✅ | Eintrag hinzufügen (Client-ID möglich, idempotent) |
| GET | `/api/households/{id}/shopping-items/stores` | ✅ | Distinct Geschäfte (ohne Beachtung der Schreibweise) |
| POST | `/api/households/{id}/shopping-items/reassign-store` | ✅ | Geschäft umbenennen/auflösen (Bulk-Update) |
| PATCH | `/api/households/{id}/shopping-items/{item_id}` | ✅ | Eintrag aktualisieren |
| DELETE | `/api/households/{id}/shopping-items/{item_id}` | ✅ | Eintrag löschen |
| **Todos** | | | |
| GET | `/api/households/{id}/todos/` | ✅ | Todo-Liste |
| POST | `/api/households/{id}/todos/` | ✅ | Todo erstellen (Client-ID möglich, idempotent) |
| PATCH | `/api/households/{id}/todos/{todo_id}` | ✅ | Todo aktualisieren |
| DELETE | `/api/households/{id}/todos/{todo_id}` | ✅ | Todo löschen |
| POST | `/api/households/{id}/todos/{todo_id}/claim` | ✅ | Todo übernehmen |
| POST | `/api/households/{id}/todos/{todo_id}/reminders/` | ✅ | Erinnerung anlegen (maximal 5 pro Todo; nicht an erledigte Todos → 422 `TODO_IS_DONE`; `remind_at` ohne Offset = Wanduhrzeit des Haushalts, wie bei Terminen; Vergangenheit → 422 `REMINDER_IN_PAST`). Erledigen markiert Erinnerungen nicht mehr; Wiedereröffnen schaltet künftige wieder scharf |
| DELETE | `/api/households/{id}/todos/{todo_id}/reminders/{reminder_id}` | ✅ | Erinnerung löschen |
| **Expenses** | | | |
| GET | `/api/households/{id}/expenses/` | ✅ | Ausgaben-Liste (nach Datum absteigend, `limit`/`offset`, optional `month`; `deleted=true` → nur gelöschte) |
| GET | `/api/households/{id}/expenses/{expense_id}` | ✅ | Einzelne Ausgabe (auch gelöscht) |
| POST | `/api/households/{id}/expenses/` | ✅ | Ausgabe erstellen (even/custom Split) |
| GET | `/api/households/{id}/expenses/balances` | ✅ | Salden + Ausgleichsvorschläge (Greedy-Algorithmus) |
| PATCH | `/api/households/{id}/expenses/{expense_id}` | ✅ | Ausgabe aktualisieren (optional Shares neu berechnen; `If-Match: <version>` → 409 bei veraltetem Stand) |
| DELETE | `/api/households/{id}/expenses/{expense_id}` | ✅ | Ausgabe löschen (Soft Delete, idempotent; Shares bleiben für das Wiederherstellen) |
| POST | `/api/households/{id}/expenses/{expense_id}/restore` | ✅ | Gelöschte Ausgabe exakt wiederherstellen (409 `BILL_ALREADY_BOOKED`, wenn der Monat inzwischen neu gebucht wurde) |
| **Settlements** | | | |
| GET | `/api/households/{id}/settlements/` | ✅ | Ausgleichszahlungen (`limit`/`offset`; `deleted=true` → nur gelöschte) |
| POST | `/api/households/{id}/settlements/check` | ✅ | Plausibilität prüfen ohne Speichern (`DUPLICATE_RECENT`, `EXCEEDS_OPEN_DEBT`) |
| POST | `/api/households/{id}/settlements/` | ✅ | Ausgleichszahlung erstellen (Client-`id` idempotent; Antwort mit `warnings`) |
| DELETE | `/api/households/{id}/settlements/{settlement_id}` | ✅ | Ausgleichszahlung löschen (Soft Delete) |
| POST | `/api/households/{id}/settlements/{settlement_id}/restore` | ✅ | Gelöschte Ausgleichszahlung wiederherstellen |
| **Budget und wiederkehrende Rechnungen** | | | |
| GET | `/api/households/{id}/budget` | ✅ | Budget eines Monats (`month`, Default aktueller Monat) |
| PUT | `/api/households/{id}/budget` | ✅ | Budget eines Monats setzen (Upsert) |
| DELETE | `/api/households/{id}/budget` | ✅ | Budget eines Monats löschen (`month`, 204) |
| GET | `/api/households/{id}/recurring-bills/` | ✅ | Wiederkehrende Rechnungen (`include_inactive`) |
| POST | `/api/households/{id}/recurring-bills/` | ✅ | Rechnung erstellen |
| PATCH | `/api/households/{id}/recurring-bills/{bill_id}` | ✅ | Rechnung aktualisieren |
| DELETE | `/api/households/{id}/recurring-bills/{bill_id}` | ✅ | Rechnung löschen |
| POST | `/api/households/{id}/recurring-bills/{bill_id}/book` | ✅ | Rechnung als Ausgabe buchen (eine Buchung pro Rechnung und Monat; optional `month` bis 12 Monate zurück) |
| **Chores** | | | |
| GET | `/api/households/{id}/chores/` | ✅ | Ämtli-Liste (inkl. inaktive) |
| POST | `/api/households/{id}/chores/` | ✅ | Ämtli erstellen (Validierung, `anchor_date`) |
| PATCH | `/api/households/{id}/chores/{chore_id}` | ✅ | Ämtli aktualisieren. Zeitplanänderung → offene künftige Zuweisungen gelöscht, neu ab `anchor_date` (nie überfällig); Pausieren → offene Zuweisungen ab heute gelöscht (Rotationsplätze zurück); Reaktivieren → neuer `anchor_date` ab heute, kein Nachholen (PD-C1) |
| DELETE | `/api/households/{id}/chores/{chore_id}` | ✅ | Ämtli + Zuweisungen löschen |
| GET | `/api/households/{id}/chores/assignments` | ✅ | Zuweisungen (`from`/`to`; triggert Materialisierung, Fenster max. 92 Tage) |
| POST | `/api/households/{id}/chores/assignments/{assignment_id}/complete` | ✅ | Zuweisung abhaken (idempotent) |
| POST | `/api/households/{id}/chores/assignments/{assignment_id}/uncomplete` | ✅ | Abhaken rückgängig (idempotent) |
| PATCH | `/api/households/{id}/chores/assignments/{assignment_id}` | ✅ | Neu zuweisen (User muss Mitglied sein) |
| **Kalender und Termine** | | | |
| GET | `/api/households/{id}/calendars/` | ✅ | Kalender-Liste |
| POST | `/api/households/{id}/calendars/` | ✅ | Kalender erstellen |
| PATCH | `/api/households/{id}/calendars/{calendar_id}` | ✅ | Kalender aktualisieren |
| DELETE | `/api/households/{id}/calendars/{calendar_id}` | ✅ | Kalender löschen |
| GET | `/api/households/{id}/events/` | ✅ | Termine im Zeitraum (`from_date`, `to_date` Pflicht) |
| POST | `/api/households/{id}/events/` | ✅ | Termin erstellen |
| GET | `/api/households/{id}/events/{event_id}` | ✅ | Termin lesen |
| PATCH | `/api/households/{id}/events/{event_id}` | ✅ | Termin aktualisieren |
| DELETE | `/api/households/{id}/events/{event_id}` | ✅ | Termin löschen |
| **Abstimmungen** | | | |
| GET | `/api/households/{id}/polls/` | ✅ | Abstimmungen (Filter `status`) |
| POST | `/api/households/{id}/polls/` | ✅ | Abstimmung erstellen (Termin- oder Essens-Umfrage) |
| GET | `/api/households/{id}/polls/{poll_id}` | ✅ | Abstimmung lesen |
| DELETE | `/api/households/{id}/polls/{poll_id}` | ✅ | Abstimmung löschen |
| POST | `/api/households/{id}/polls/{poll_id}/vote` | ✅ | Abstimmen (eine Stimme pro Person und Abstimmung) |
| POST | `/api/households/{id}/polls/{poll_id}/decide` | ✅ | Terminumfrage entscheiden → legt einen Termin an |
| POST | `/api/households/{id}/polls/{poll_id}/meal-decide` | ✅ | Essensumfrage entscheiden → Wochenmenü-Eintrag |
| **Haustiere** | | | |
| GET | `/api/households/{id}/pets/` | ✅ | Haustiere |
| POST | `/api/households/{id}/pets/` | ✅ | Haustier anlegen |
| GET | `/api/households/{id}/pets/feeding-status` | ✅ | Fütterungsstatus aller Tiere (heute) |
| POST | `/api/households/{id}/pets/feed-all` | ✅ | Alle Tiere füttern |
| GET | `/api/households/{id}/pets/{pet_id}` | ✅ | Haustier lesen |
| PATCH | `/api/households/{id}/pets/{pet_id}` | ✅ | Haustier aktualisieren (inkl. `photo_file_id`) |
| DELETE | `/api/households/{id}/pets/{pet_id}` | ✅ | Haustier löschen |
| POST | `/api/households/{id}/pets/{pet_id}/feedings` | ✅ | Fütterung erfassen |
| DELETE | `/api/households/{id}/pets/{pet_id}/feedings/{feeding_id}` | ✅ | Fütterung löschen |
| GET | `/api/households/{id}/pets/{pet_id}/medications` | ✅ | Medikamente |
| POST | `/api/households/{id}/pets/{pet_id}/medications` | ✅ | Medikament anlegen |
| PATCH | `/api/households/{id}/pets/{pet_id}/medications/{medication_id}` | ✅ | Medikament aktualisieren |
| DELETE | `/api/households/{id}/pets/{pet_id}/medications/{medication_id}` | ✅ | Medikament löschen |
| POST | `/api/households/{id}/pets/{pet_id}/medications/{medication_id}/give` | ✅ | Verabreichung erfassen |
| GET | `/api/households/{id}/pets/{pet_id}/medications/{medication_id}/log` | ✅ | Verabreichungs-Log |
| GET | `/api/households/{id}/pets/{pet_id}/care-tasks/` | ✅ | Pflegeaufgaben |
| POST | `/api/households/{id}/pets/{pet_id}/care-tasks/` | ✅ | Pflegeaufgabe anlegen |
| PATCH | `/api/households/{id}/pets/{pet_id}/care-tasks/{task_id}` | ✅ | Pflegeaufgabe aktualisieren |
| DELETE | `/api/households/{id}/pets/{pet_id}/care-tasks/{task_id}` | ✅ | Pflegeaufgabe löschen |
| POST | `/api/households/{id}/pets/{pet_id}/care-tasks/{task_id}/complete` | ✅ | Pflegeaufgabe erledigen (nächste Fälligkeit wird berechnet) |
| **Essen** | | | |
| GET | `/api/households/{id}/recipes/` | ✅ | Rezepte |
| POST | `/api/households/{id}/recipes/` | ✅ | Rezept anlegen |
| GET | `/api/households/{id}/recipes/{recipe_id}` | ✅ | Rezept lesen |
| PATCH | `/api/households/{id}/recipes/{recipe_id}` | ✅ | Rezept aktualisieren |
| DELETE | `/api/households/{id}/recipes/{recipe_id}` | ✅ | Rezept löschen |
| GET | `/api/households/{id}/meal-plan/` | ✅ | Wochenmenü (`week`: beliebiges Datum der Woche) |
| PUT | `/api/households/{id}/meal-plan/{entry_date}` | ✅ | Tageseintrag setzen (Rezept oder Freitext) |
| DELETE | `/api/households/{id}/meal-plan/{entry_date}` | ✅ | Tageseintrag löschen |
| POST | `/api/households/{id}/meal-plan/{entry_id}/add-missing-to-shopping` | ✅ | Fehlende Zutaten auf die Einkaufsliste setzen |
| **Notizen** | | | |
| GET | `/api/households/{id}/notes/` | ✅ | Notizen |
| POST | `/api/households/{id}/notes/` | ✅ | Notiz erstellen |
| PATCH | `/api/households/{id}/notes/{note_id}` | ✅ | Notiz aktualisieren |
| DELETE | `/api/households/{id}/notes/{note_id}` | ✅ | Notiz löschen |
| **Dateien** | | | |
| POST | `/api/households/{id}/files/` | ✅ | Datei hochladen (JPEG/PNG/WebP/HEIC/HEIF/PDF, max. 10 MB; Bilder vor dem Decode auf 25 MP geprüft und auf 1600 px verkleinert; Speicher-Limit pro Haushalt) |
| GET | `/api/households/{id}/files/{file_id}` | ✅ | Datei herunterladen (JWT-geschützt) |
| DELETE | `/api/households/{id}/files/{file_id}` | ✅ | Datei löschen (204; `FILE_IN_USE`, wenn noch referenziert) |
| **Dokumente** | | | |
| GET | `/api/households/{id}/documents/` | ✅ | Dokumente (`category`, Suche `q`, `limit`/`offset`) |
| POST | `/api/households/{id}/documents/` | ✅ | Dokument aus bereits hochgeladenen Dateien anlegen (max. 30 Dateien) |
| POST | `/api/households/{id}/documents/upload` | ✅ | Dokument mit Datei-Upload (mehrseitig) anlegen |
| GET | `/api/households/{id}/documents/storage` | ✅ | Speicher-Auslastung des Haushalts |
| GET | `/api/households/{id}/documents/{document_id}` | ✅ | Dokument lesen (inkl. Seiten) |
| PATCH | `/api/households/{id}/documents/{document_id}` | ✅ | Dokument aktualisieren |
| DELETE | `/api/households/{id}/documents/{document_id}` | ✅ | Dokument löschen (204) |
| POST | `/api/households/{id}/documents/{document_id}/files` | ✅ | Seiten hinzufügen |
| PUT | `/api/households/{id}/documents/{document_id}/files/order` | ✅ | Seiten umsortieren |
| DELETE | `/api/households/{id}/documents/{document_id}/files/{file_id}` | ✅ | Seite entfernen |
| **Web Push** | | | |
| GET | `/api/push/config` | ✅ | Push-Konfiguration (öffentlicher VAPID-Schlüssel, aktiv/inaktiv) |
| POST | `/api/push/subscriptions` | ✅ | Gerät anmelden (idempotent pro Endpoint) |
| DELETE | `/api/push/subscriptions` | ✅ | Gerät abmelden (idempotent, 204) |
| POST | `/api/push/test` | ✅ | Test-Benachrichtigung an die eigenen Geräte; Rate-Limit 5/Minute |
| **Tags (NFC/QR)** | | | |
| GET | `/api/households/{id}/tags/` | ✅ | Tags des Haushalts (inkl. Token, Zielname) |
| GET | `/api/households/{id}/tags/targets` | ✅ | Zieltypen mit Aktionen und Zielen (Formular) |
| POST | `/api/households/{id}/tags/` | ✅ Admin | Tag anlegen (Token erzeugt der Server) |
| PATCH | `/api/households/{id}/tags/{tag_id}` | ✅ Admin | Bezeichnung, aktiv/deaktiviert, Ziel/Aktion neu zuordnen |
| POST | `/api/households/{id}/tags/{tag_id}/regenerate-token` | ✅ Admin | Neuer Token, alter Chip/QR-Code wird wirkungslos |
| DELETE | `/api/households/{id}/tags/{tag_id}` | ✅ Admin | Tag löschen |
| POST | `/api/tags/resolve/{token}` | ✅ Mitglied | Was der Tag tut (keine Mutation; 30/min/IP); liefert `confirm` (angezeigte Zuweisung bzw. Gießaufgaben) |
| POST | `/api/tags/{token}/execute` | ✅ Mitglied | Aktion ausführen (30/min/IP). `chore.assignment.done` und `plant.water` verlangen `confirm` aus resolve (fehlt → 422 `TAG_CONFIRMATION_REQUIRED`, veraltet → 409 `TAG_CONFIRMATION_STALE`). Idempotent pro Haushaltstag: schon erledigt → `changed=false`, `reason=ALREADY_DONE` |
| **Health** | | | |
| GET | `/api/health` | ❌ | Health-Check mit DB-Prüfung |

### Socket.IO Events

Verbindung unter `/socket.io` mit `auth: { token }` (Access-Token). Events gehen an den Raum `household_{id}`; ein Client betritt ihn mit `join_household` (Mitgliedschaft wird geprüft). Wird ein Mitglied entfernt, wirft der Server seine Verbindungen nach dem Event `household_member_removed` aus dem Raum. Server-seitige Fehler beim Beitritt kommen als Event `error` (`{ message }`) an den Client.

| Event | Richtung | Payload |
|---|---|---|
| `join_household` | Client → Server | `{ household_id }` → Ack (leer); kam vorher kein `error`, ist der Raum betreten |
| `leave_household` | Client → Server | `{ household_id }` |
| `error` | Server → Client | `{ message }` — Client zeigt den Sync-Punkt gelb und versucht den Beitritt erneut (2 s … 60 s, max. 5×) |
| **Sitzung** | | |
| `reauth` | Client → Server | `{ token }` → Ack `{ ok }` |
| `session_ended` | Server → Client (eine Verbindung) | `{ reason: "expired" \| "logout" \| "revoked" }`, danach trennt der Server |
| **Haushalt** | | |
| `household_updated` | Server → Room | `{ id, name }` |
| `household_member_joined` | Server → Room | `{ household_id, user_id, display_name, role }` |
| `household_member_left` | Server → Room | `{ household_id, user_id }` |
| `household_member_removed` | Server → Room | `{ household_id, user_id }` |
| **Einkauf** | | |
| `shopping_list_created` | Server → Room | `ShoppingList` (auch beim Übernehmen fehlender Zutaten) |
| `shopping_list_updated` | Server → Room | `ShoppingList` |
| `shopping_list_deleted` | Server → Room | `{ id }` |
| `shopping_item_created` | Server → Room | `ShoppingItem` |
| `shopping_item_updated` | Server → Room | `ShoppingItem` |
| `shopping_item_deleted` | Server → Room | `{ id }` |
| `shopping_items_bulk_updated` | Server → Room | `{ item_ids, changes: { store } }` |
| **Todos** | | |
| `todo_created` | Server → Room | `TodoItem` |
| `todo_updated` | Server → Room | `TodoItem` (auch bei Claim und Erinnerungen; Erinnerung anlegen/löschen erhöht `version`) |
| `todo_deleted` | Server → Room | `{ id }` |
| **Expenses** | | |
| `expense_created` | Server → Room | `ExpenseResponse` (inkl. shares, `version`; auch beim Buchen einer Rechnung und beim Wiederherstellen) |
| `expense_updated` | Server → Room | `ExpenseResponse` (inkl. shares, `version`) |
| `expense_deleted` | Server → Room | `{ id, household_id, deleted_by_user_id, version }` (Soft Delete) |
| **Settlements** | | |
| `settlement_created` | Server → Room | `SettlementResponse` (auch beim Wiederherstellen) |
| `settlement_deleted` | Server → Room | `{ id, household_id, deleted_by_user_id }` (Soft Delete) |
| **Budget und Rechnungen** | | |
| `budget_updated` | Server → Room | `BudgetResponse` |
| `budget_deleted` | Server → Room | `{ household_id, month }` |
| `recurring_bill_created` | Server → Room | `RecurringBillResponse` |
| `recurring_bill_updated` | Server → Room | `RecurringBillResponse` |
| `recurring_bill_deleted` | Server → Room | `{ id, household_id }` |
| `recurring_bill_booked` | Server → Room | `{ bill_id, expense_id, household_id, booked_month }` |
| **Chores** | | |
| `chore_created` | Server → Room | `ChoreResponse` |
| `chore_updated` | Server → Room | `ChoreResponse` |
| `chore_deleted` | Server → Room | `{ id, household_id }` |
| `chore_assignment_created` | Server → Room | `ChoreAssignmentResponse` — bei jeder Materialisierung (Putzplan, Tag-Scan, Push-Scheduler, Zeitplanänderung) |
| `chore_assignment_updated` | Server → Room | `ChoreAssignmentResponse` (abhaken, rückgängig, neu zuweisen) |
| `chore_assignments_deleted` | Server → Room | `{chore_id, household_id, ids}` — Zeitplanänderung oder Pause hat offene Zuweisungen gelöscht; Clients entfernen sie |
| **Kalender** | | |
| `calendar_created` | Server → Room | `CalendarResponse` |
| `calendar_updated` | Server → Room | `CalendarResponse` |
| `calendar_deleted` | Server → Room | `{ id }` |
| `event_created` | Server → Room | `EventResponse`; nach `decide` einer Umfrage `{ id, title }` |
| `event_updated` | Server → Room | `EventResponse` |
| `event_deleted` | Server → Room | `{ id }` |
| **Abstimmungen** | | |
| `poll_created` | Server → Room | `PollResponse` |
| `poll_voted` | Server → Room | `PollResponse` |
| `poll_decided` | Server → Room | `PollResponse` (Termin- und Essensumfragen) |
| `poll_deleted` | Server → Room | `{ id }` |
| **Haustiere** | | |
| `pet_created` | Server → Room | `PetResponse` |
| `pet_updated` | Server → Room | `PetResponse` |
| `pet_deleted` | Server → Room | `{ id, household_id }` |
| `feeding_created` | Server → Room | `FeedingLogResponse` (auch bei „Alle füttern“) |
| `feeding_deleted` | Server → Room | `{ id, pet_id, household_id }` |
| `medication_created` | Server → Room | `MedicationResponse` |
| `medication_updated` | Server → Room | `MedicationResponse` |
| `medication_deleted` | Server → Room | `{ id, pet_id, … }` |
| `medication_given` | Server → Room | `MedicationLogResponse` |
| `pet_care_task_created` | Server → Room | `CareTaskResponse` |
| `pet_care_task_updated` | Server → Room | `CareTaskResponse` (auch beim Erledigen) |
| `pet_care_task_deleted` | Server → Room | `{ id, pet_id }` |
| **Essen** | | |
| `recipe_created` | Server → Room | `RecipeResponse` |
| `recipe_updated` | Server → Room | `RecipeResponse` |
| `recipe_deleted` | Server → Room | `{ id }` |
| `meal_plan_updated` | Server → Room | `MealPlanEntryResponse`; nach `meal-decide` `{ date }` |
| `meal_plan_deleted` | Server → Room | `{ date }` |
| **Notizen** | | |
| `note_created` | Server → Room | `NoteResponse` |
| `note_updated` | Server → Room | `NoteResponse` |
| `note_deleted` | Server → Room | `{ id }` |
| **Dateien und Dokumente** | | |
| `file_uploaded` | Server → Room | `StoredFileResponse` |
| `file_deleted` | Server → Room | `{ id }` |
| `document_created` | Server → Room | `DocumentResponse` |
| `document_updated` | Server → Room | `DocumentResponse` (auch bei Seiten-Änderungen) |
| `document_deleted` | Server → Room | `{ id, file_ids }` |

Der Client verarbeitet `budget_deleted`, `file_uploaded` und `file_deleted` nicht (kein Handler im Frontend). Web Push (Todo-Erinnerungen, Tier- und Pflanzenpflege, Putzplan, Dokument-Ablauf) läuft nicht über Socket.IO, sondern über `/api/push/…` und den Scheduler im Backend. Push-URLs tragen den Haushalt (`?hh=<id>`); der Router wechselt beim Öffnen in diesen Haushalt (CASA-40).

### Lebensdauer einer Socket-Verbindung

Eine Verbindung gilt nur so lange wie das Access-Token (15 Min.), mit dem sie zuletzt authentifiziert wurde.

- **connect:** Der Server prüft das JWT, merkt sich `user_id` und `exp` in der Socket-Session, legt die Verbindung in den persönlichen Raum `user_<id>` und startet einen Timer auf `exp`.
- **Verlängern:** Nach jedem Token-Refresh (Axios-Interceptor, Cross-Tab-Sync) schickt der Client `reauth` mit dem neuen Token. Gehört es zum selben User, setzt der Server `exp` und Timer neu. Die Verbindung bleibt bestehen, Räume bleiben erhalten; früher baute der Client bei jedem Refresh eine neue Verbindung auf.
- **Ablauf:** Läuft der Timer ab, schickt der Server `session_ended` (`expired`) und trennt. `join_household` prüft `exp` zusätzlich. Der Client holt sich per Refresh ein neues Token und verbindet neu; die Reconnect-Callbacks treten dem Haushalts-Raum wieder bei und laden die Daten nach.
- **Logout:** `/api/auth/logout` trennt alle Verbindungen des Users (`session_ended` mit `logout`); die Reuse-Detection in `/refresh` trennt mit `revoked`. Der Access-Token kennt kein Gerät, deshalb trifft das auch andere Geräte. Diese verbinden sich mit ihrem noch gültigen Access-Token sofort neu, aber **ohne** Refresh: Der Refresh-Token könnte gerade widerrufen sein (z. B. zweiter Tab im selben Browser), ein Refresh würde dann die Reuse-Detection auslösen und alle Geräte abmelden. Das ausloggende Gerät trennt seinen Socket schon vor dem Logout-Aufruf und verbindet nicht neu.
- **Abgelehnter Connect** (z. B. Token abgelaufen): höchstens ein Refresh-Versuch bis zur nächsten erfolgreichen Verbindung, kein Endlos-Loop.

**Warum `exp` + Timer + `reauth` (und nicht nur eine Prüfung bei jedem Event):** Fast der ganze Verkehr läuft vom Server zum Client; ein Client, der nur zuhört, schickt nach `join_household` keine Events mehr und würde bei reiner Event-Prüfung nie getrennt. Ohne `reauth` wiederum müsste jede Verbindung alle 15 Minuten neu aufgebaut werden. Der Client erneuert sein Token ohnehin über den Axios-Interceptor; `reauth` gibt das Ergebnis nur an den Socket weiter.

**Client (`composables/useRealtimeSession.ts`, `useSocket.ts`):** Ein Token-Refresh gibt nur das neue Token per `reauth` weiter; die Stores werden **nur** bei Anmeldung, Haushaltswechsel und Reconnect nachgeladen (CASA-44). Der Sync-Punkt zeigt „Verbunden“ erst, wenn auch `join_household` bestätigt ist (`useSyncStatus`, CASA-46). Payloads mit `household_id` eines anderen als des aktuellen Haushalts verwirft `useSocket.on` (CASA-12).

**Grenze:** Ein Access-Token bleibt bis zu seinem Ablauf gültig (zustandsloses JWT). Wer es hat, kann sich nach dem Logout bis zu 15 Minuten lang neu verbinden, genau wie bei der REST-API. Danach endet jede Verbindung spätestens mit dem Ablauf des Tokens. Timer und Räume liegen im Prozessspeicher (ein Worker, siehe Abschnitt 8).
| **Tags** | | |
| `tag_created` | Server → Room | `TagResponse` |
| `tag_updated` | Server → Room | `TagResponse` (auch nach jeder Nutzung: `use_count`, `last_used_at`) |
| `tag_deleted` | Server → Room | `{ id, household_id }` |

---

## 5. Datenmodell

32 Tabellen in `backend/app/models.py` (Alembic-Migrationen: `backend/migrations/versions/`, 33 Versionen). Geldbeträge sind Integer in Rappen (`*_rappen`). Soweit nicht anders vermerkt, haben alle Haushalts-Tabellen `household_id` (FK auf `households`, `ON DELETE CASCADE`).

### Übersicht

```
User ──< HouseholdMember >── Household
 ├──< RefreshToken                │  (invite_code, timezone, currency)
 └──< PushSubscription            │
                                  ├── ShoppingList ──< ShoppingItem
                                  ├── Todo ──< TodoReminder
                                  ├── Expense ──< ExpenseShare   (Expense >── RecurringBill, optional)
                                  ├── Settlement, Budget, RecurringBill
                                  ├── Chore ──< ChoreAssignment
                                  ├── Calendar ──< Event
                                  ├── EventPoll ──< EventPollOption ──< EventPollVote
                                  ├── Pet ──< FeedingLog, Medication ──< MedicationLog, PetCareTask
                                  ├── Recipe, MealPlanEntry (>── Recipe)
                                  ├── Note
                                  └── StoredFile >──< Document   (über DocumentFile; Pet.photo_file_id → StoredFile)
```

### Tabellen

| Tabelle | Wichtige Felder | Beziehungen / Regeln |
|---|---|---|
| `households` | `name`, `invite_code` (unique), `timezone` (Default `Europe/Zurich`), `currency` (Default `CHF`) | Wurzel aller Haushalts-Daten |
| `users` | `email` (unique), `password_hash`, `display_name` | |
| `household_members` | `household_id`, `user_id`, `role` (`admin`/`member`), `joined_at` | Unique `(household_id, user_id)` |
| `refresh_tokens` | `user_id`, `token_hash` (unique), `expires_at`, `revoked_at`, `replaced_by_id` | Rotation mit Reuse-Erkennung; `user_id` CASCADE |
| `push_subscriptions` | `user_id`, `endpoint` (unique), `p256dh`, `auth`, `locale` | Web-Push-Geräte; `user_id` CASCADE |
| `shopping_lists` | `name`, `icon`, `position` | `version`/`updated_at` |
| `shopping_items` | `list_id` (CASCADE), `name`, `quantity`, `category`, `store` (Freitext), `is_checked`, `checked_at`, `added_by_user_id`, `assigned_to_user_id` | `version`/`updated_at`; Geschäfte sind abgeleitete Freitext-Werte, keine eigene Tabelle |
| `todos` | `title`, `description`, `assigned_to_user_id`, `due_date`, `is_done`, `done_at`, `tags` (JSON), `created_by_user_id` | `version`/`updated_at` |
| `todo_reminders` | `todo_id` (CASCADE), `remind_at`, `notified_at` | Maximal 5 pro Todo (API); Index `(household_id, remind_at)` |
| `expenses` | `description`, `amount_rappen`, `currency`, `split_type` (`even`/`custom`), `category`, `paid_by_user_id`, `expense_date`, `recurring_bill_id`, `booked_month` | `updated_at` (kein `version`); Unique `(recurring_bill_id, booked_month)` (eine Buchung pro Rechnung und Monat); Index `(household_id, expense_date)` |
| `expense_shares` | `expense_id` (CASCADE), `user_id`, `amount_rappen` | Unique `(expense_id, user_id)` |
| `settlements` | `from_user_id`, `to_user_id`, `amount_rappen`, `currency`, `settled_date`, `note`, `created_by_user_id` | Index `(household_id, settled_date)` |
| `budgets` | `month` (1. des Monats), `amount_rappen` | `updated_at`; Unique `(household_id, month)` |
| `recurring_bills` | `name`, `amount_rappen`, `day_of_month`, `category`, `split_type`, `active`, `paid_by_user_id` | Standard-Zahler beim Buchen |
| `chores` | `title`, `description`, `recurrence` (`weekly`/`biweekly`/`monthly`), `weekday`, `day_of_month`, `rotation_order` (JSON), `next_rotation_index`, `anchor_date`, `active` | |
| `chore_assignments` | `chore_id` (CASCADE), `assigned_user_id`, `due_date`, `completed_at`, `completed_by_user_id` | `version`/`updated_at`; Unique `(chore_id, due_date)`; Index `(household_id, due_date)` |
| `calendars` | `name`, `color`, `position` | |
| `events` | `calendar_id` (CASCADE), `title`, `starts_at`, `ends_at`, `all_day`, `participant_ids`, `note` | Zeiten UTC, Wanduhrzeit in Haushalts-Zeitzone; Index `(household_id, starts_at)` |
| `event_polls` | `question`, `status`, `poll_type` (`event`/`meal`), `decided_event_id`, `decided_meal_date` | |
| `event_poll_options` | `poll_id` (CASCADE), `label`, `starts_at`, `recipe_id` | |
| `event_poll_votes` | `poll_id`, `option_id` (CASCADE), `user_id` | Unique `(option_id, user_id)` und `(poll_id, user_id)` (eine Stimme pro Person und Abstimmung) |
| `pets` | `name`, `species`, `breed`, `birthdate`, `weight_grams`, `photo_url`, `photo_file_id`, `chip_number`, `insurance`, `vet_name`, `food_notes`, `health_entries`, `notes` | `photo_file_id` → `stored_files` (SET NULL) |
| `feeding_logs` | `pet_id` (CASCADE), `slot`, `date`, `fed_at`, `fed_by_user_id` | Unique `(pet_id, date, slot)` |
| `medications` | `pet_id` (CASCADE), `name`, `dosage`, `schedule`, `active` | |
| `medication_logs` | `medication_id` (CASCADE), `given_at`, `given_by_user_id` | |
| `pet_care_tasks` | `pet_id` (CASCADE), `name`, `interval_days`, `next_due_at`, `last_done_at`, `notified_at` | Push-Erinnerung bei Fälligkeit |
| `recipes` | `name`, `servings`, `cost_rappen`, `duration_min`, `ingredients`, `is_favorite` | |
| `meal_plan_entries` | `date`, `recipe_id` (SET NULL), `free_text` | Unique `(household_id, date)` |
| `notes` | `title`, `body`, `tag`, `pinned`, `created_by_user_id` | `updated_at` |
| `stored_files` | `original_name`, `mime_type`, `size_bytes`, `storage_path`, `uploaded_by_user_id` | Datei liegt unter `UPLOAD_DIR/{household_id}/` |
| `documents` | `title`, `category`, `notes`, `document_date`, `expiry_date`, `created_by_user_id` | `updated_at`; Index `(household_id, category)` |
| `document_files` | `document_id`, `file_id` (beide CASCADE), `position` | Seiten eines Dokuments; `file_id` unique (eine Datei gehört zu höchstens einem Dokument) |

Verweise auf `users` in Ersteller-, Zuweiser- und Zahler-Spalten (`created_by_user_id`, `assigned_to_user_id`, `paid_by_user_id` …) sind `ON DELETE SET NULL`. Beim Verlassen eines Haushalts bleiben Ausgaben und Anteile des Ex-Mitglieds bestehen („Ehemaliges Mitglied“-Muster, siehe Geschäftsregeln).

### Synchronisations-Felder (`version` / `updated_at`)

`SyncVersionMixin` (`backend/app/models.py`) fügt `updated_at` und `version` hinzu (`version` startet bei 1 und wird bei jeder Änderung serverseitig erhöht). Er ist auf vier Tabellen aktiv: `shopping_lists`, `shopping_items`, `todos`, `chore_assignments`. Die Clients verwerfen damit veraltete Socket-Events. Nur `updated_at` (ohne `version`) haben `expenses`, `budgets`, `notes` und `documents`; alle anderen Tabellen haben keines von beiden.

### Invarianten

- `SUM(expense_shares.amount_rappen) == expenses.amount_rappen` (im Service-Layer erzwungen, nicht als DB-Constraint).
- PATCH: ein weggelassenes Feld bleibt unverändert, `null` leert es — für NOT-NULL-Spalten antwortet die API mit 422 (`PatchModel`). Ausnahme: `ingredients`/`steps`/`tags` von Rezepten, dort wird `null` zu `[]`. NOT-NULL-JSON-Spalten speichern Python-`None` nie als JSON-`null` (`JSON(none_as_null=True)`); Altlasten repariert Migration `fnd1a2b3c4d5`.
- Parallele Schreibkonflikte, die nicht fachlich behandelt werden, liefern 409 `CONFLICT_RETRY` (Frontend: „bitte noch einmal versuchen“) statt 500.
- `households.timezone` (Default `Europe/Zurich`) steuert Putzplan-Datumsberechnung, Termin-Uhrzeiten, Fütterungs-/Pflegetage sowie die Kalenderdaten der Finanzen (Buchungsmonat, Default-Monat von Budget und Übersicht, Standard-Datum von Ausgaben/Ausgleich; `services/household_time.py`); `households.currency` (Default `CHF`): eine Währung pro Haushalt.
- Beim Löschen eines Haushalts werden alle zugehörigen Tabellen per `CASCADE` geleert; die Dateien auf dem Datenträger entfernt der Router beim Auflösen des Haushalts (`POST /leave` durch das letzte Mitglied); verwaiste Uploads räumt `app/services/file_cleanup.py` periodisch auf.
- **Ledger-FKs auf `users` sind `RESTRICT`** (Migration `ops1a2b3c4d5`, CASA-55): `expense_shares.user_id`, `settlements.from_user_id`/`to_user_id`, `expenses.paid_by_user_id`. Ein `DELETE FROM users` mit Buchungen schlägt fehl, statt Anteile/Ausgleiche still mitzulöschen (früher `CASCADE`: Salden der anderen hätten sich verschoben) oder den Zahler zu leeren (`SET NULL`). Festgehalten in `tests/pg/test_pg_smoke.py::test_ledger_user_fks_restrict`.
- **Konto-Löschung (PD-D1, nur vorbereitet — kein Endpunkt):** Eine künftige Löschung *anonymisiert* die Person, statt die `users`-Zeile zu löschen: `email` → nicht zustellbarer Platzhalter (z. B. `deleted-<uuid>@invalid`), `display_name` → „Ehemaliges Mitglied“, `password_hash` unbrauchbar, Refresh-Tokens/Push-Abos/Widget-Tokens/`ai_user_usage` löschen, Mitgliedschaften wie beim Verlassen beenden (Departure-Regeln). Alle Buchungen, Logs und Historien behalten die (anonyme) `user_id`, Salden bleiben unverändert. Die übrigen `NO ACTION`-FKs (Termine, Abstimmungen, Fütterungs-/Medikamenten-Logs, Mitgliedschaften) blockieren eine Hard-Delete-Abkürzung bewusst.
- **Schema = Modelle** (CASA-56): Jeder DB-Server-Default hat ein Modell-Pendant (`server_default`); der Drift-Check `tests/pg/test_pg_smoke.py::test_models_match_migrations` vergleicht Tabellen, Spalten, Typen, Nullability, FKs **und** Server-Defaults. Alle Migrationen lassen sich bis `base` zurückrollen (`test_full_downgrade_to_base_and_upgrade_again`) — im Betrieb gilt trotzdem forward-only (siehe `docs/deployment.md` §4).

---

---

## Geschäftsregeln

- Einladungscodes laufen nach 7 Tagen ab (`INVITE_CODE_TTL` in `services/invite_code.py`). Das Ablaufdatum steht in `households.invite_code_expires_at` (UTC); es wird beim Anlegen des Haushalts und bei jeder Rotation (Admin-Button, Entfernen eines Mitglieds) neu gesetzt. `NULL` bedeutet „läuft nicht ab“. Ein abgelaufener Code wird bei `POST /join` und `POST /register` mit HTTP 410 und `INVITE_CODE_EXPIRED` abgelehnt (nicht als „nicht gefunden“). Die Migration setzt bei bestehenden Haushalten 7 Tage ab Upgrade; die Haushalts-Ansicht zeigt „gültig bis …“ bzw. einen Hinweis mit Link zur Rotation.
### Währungsregel
- **Eine Währung pro Haushalt** (`Household.currency`, Default: CHF)
- Expenses und Settlements müssen die Haushaltswährung verwenden
- Fremdwährungs-Mismatch → 422 CURRENCY_MISMATCH
- Kein Multi-Currency (bewusste Design-Entscheidung)

### Rollen und Berechtigungen
- **Zwei Rollen:** `admin` und `member`
- Registrierung mit `household_name` → Ersteller wird `admin`
- Registrierung mit `invite_code` → Beitritt als `member`
- `POST /api/households/` → Ersteller wird `admin`
- Admin-geschützte Endpoints: PATCH Haushalt (rename), DELETE Member, Tags anlegen/ändern/löschen/Token neu erzeugen (Ausführen per Scan dürfen alle Mitglieder)
- Keine feingranularen Berechtigungen (bewusst: nur admin/member)

### Haushalt verlassen
- **Immer erlaubt**, auch mit offenem Saldo
- Expenses/Shares werden NICHT gelöscht ("Ehemaliges Mitglied"-Muster)
- Letztes Mitglied verlässt → Haushalt wird komplett gelöscht (CASCADE)
- Einziger Admin verlässt → dienstältestes verbleibendes Mitglied (frühestes `joined_at`, Tiebreaker: `user_id`) wird automatisch Admin
- Kein manueller Admin-Transfer-Dialog (Auto-Promotion-Regel reicht)

### Mitglied entfernen
- Admin darf Mitglieder mit `role="member"` entfernen
- Admin darf andere Admins NICHT entfernen → 403 CANNOT_REMOVE_ADMIN
- Sich selbst entfernen → 422 CANNOT_REMOVE_SELF (nutze /leave stattdessen)
- rotation_order in Chores wird NICHT bereinigt (Scheduler überspringt Nicht-Mitglieder)

### Registrierung
- Genau eines von `household_name` oder `invite_code` muss gesetzt sein
- `household_name` → neuer Haushalt + Admin
- `invite_code` → bestehender Haushalt + Member

---

## 6. Frontend-Architektur (Offline-Ready Pattern)

```
┌─────────────────────────────────────────────────────────┐
│  Vue Components (ShoppingList, TodoList, ChoresView...) │
│  - try/catch um Store-Actions                           │
│  - Toast-Feedback bei Rollback                          │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  Pinia Stores (shopping, todos, chores, expenses,       │
│                settlements)                              │
│  - Optimistic Updates (sofort im UI sichtbar)           │
│  - Rollback bei Server-Fehler                           │
│  - pendingTempIds (Socket-Duplikat-Schutz)              │
│  - pendingToggles (Rapid-Click-Mutex)                   │
│  - Socket-Handler: Idempotent, Server gewinnt           │
│  - Haushalts-/Sitzungs-Generation (utils/householdGuard)│
│    verwirft Antworten nach Wechsel/Logout (CASA-12)     │
│  - Create: Echo da → kein Rollback; Retry = gleiche ID  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  Repository Layer (Abstraktionsschicht)                  │
│  - ShoppingRepository Interface + Factory               │
│  - TodosRepository Interface + Factory                  │
│  - HouseholdsRepository Interface + Factory             │
│  - ExpensesRepository Interface + Factory               │
│  - SettlementsRepository Interface + Factory            │
│  - ChoresRepository Interface + Factory                 │
│  - JETZT: wraps Axios-Calls                             │
│  - DELETE: 404 = schon gelöscht = Erfolg (CASA-45)      │
│  - PHASE 2: IndexedDB + SyncQueue einhängbar            │
└──────────────────────┬──────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   ┌─────────┐  ┌───────────┐  ┌──────────────┐
   │ Axios    │  │ Socket.IO │  │ PHASE 2:     │
   │ (REST)   │  │ (Events)  │  │ IndexedDB    │
   └─────────┘  └───────────┘  └──────────────┘
```

### UI-Architektur

```
┌───────────────────────────────────────────────────┐
│  App.vue (Shell)                                    │
│  ├── Desktop ≥768px: Sticky Top-Bar                 │
│  │   Brand | Nav-Links | Household-Select | Logout  │
│  ├── Mobile <768px: Bottom-Tab-Bar (5 Tabs)         │
│  │   🛒 Einkauf | 🧹 Putzplan | ✅ Aufgaben |       │
│  │   💰 Ausgaben | 🏠 Haushalt                      │
│  ├── Offline-Banner (wenn navigator.onLine=false)   │
│  └── Toast-Container                                │
│                                                     │
│  Design-System: theme.css (CSS Custom Properties)   │
│  - Tokens: docs/design/design-tokens.md            │
│  - Akzent #896140, Teal #3D7D75, Dark Mode         │
│  - Breakpoint: 768px                                │
│  - Content max-width: 640px (zentriert)             │
│  - Touch-Targets: ≥44×44px                          │
│  - Safe-Area: env(safe-area-inset-bottom)           │
│                                                     │
│  i18n: vue-i18n, detectLocale(), DE/EN              │
└───────────────────────────────────────────────────┘
```

---

## 7. Feature-Status

### ✅ Fertig

| Feature | Backend | Frontend | Echtzeit |
|---|---|---|---|
| User-Registrierung + Login | ✅ | ✅ | — |
| Household-Erstellung (bei Registrierung) | ✅ | ✅ | — |
| Household-Beitritt (Invite-Code) | ✅ POST /join | ✅ HouseholdView | — |
| Invite-Code anzeigen | ✅ GET /invite-code | ✅ HouseholdView | — |
| Household-Mitglieder anzeigen | ✅ GET /members | ✅ HouseholdView | — |
| Household-Wechsel (Multi-Household) | — | ✅ Dropdown in App-Shell | — |
| Navigation (5 Module) | — | ✅ Tab-Bar (Mobile) + Top-Bar (Desktop) | — |
| Einkaufsliste (CRUD) | ✅ | ✅ | ✅ Socket |
| Einkaufsliste — Optimistic Updates | — | ✅ | ✅ |
| Einkaufsliste — Error-Recovery (Toast) | — | ✅ | — |
| Todo-Modul (Backend CRUD) | ✅ | ✅ | ✅ Socket |
| Todo-Frontend-UI (Komplett) | — | ✅ Quick-Add, Detail-Edit, Zuweisung, Fälligkeitsdatum | — |
| Todo-Store (Optimistic Updates) | — | ✅ | ✅ |
| Expenses-Modul (CRUD + Split + Saldo) | ✅ | ✅ ExpensesView, ExpenseList, BalanceSummary, ExpenseFormDialog | ✅ Socket |
| Settlements-Modul | ✅ | ✅ | ✅ Socket |
| Chores-Modul (Putzplan + Rotation) | ✅ | ✅ | ✅ Socket |
| i18n (DE + EN, 1173 Keys, Locale-Check) | ✅ | ✅ | — |
| Error-Code-System (maschinenlesbar) | ✅ | ✅ i18n-Mapping | — |
| Offline-Banner | — | ✅ | — |
| Toast-System | — | ✅ | — |
| Repository-Layer (Offline-Ready Seam) | — | ✅ (18 Repositories) | — |
| Race-Condition-Schutz (vom Client erzeugte IDs, versionierte Merges, Toggle-Mutex) | — | ✅ | — |
| Design-System (CSS Custom Properties) | — | ✅ theme.css + 11 UI-Komponenten | — |
| Mobile-First UI | — | ✅ Bottom-Tab-Bar, Touch-optimiert | — |
| Household erstellen (eigenständig) | ✅ POST /households/ | ✅ HouseholdView | — |
| Household umbenennen | ✅ PATCH /households/{id} | ✅ HouseholdView | ✅ Socket |
| Haushalt verlassen / Mitglied entfernen | ✅ POST /leave, DELETE /members/{uid} | ✅ HouseholdView | ✅ Socket |
| Rollen-System (admin/member) | ✅ verify_household_admin | ✅ UI-Anzeige | — |
| Währung pro Haushalt | ✅ Household.currency | ✅ /me Response | — |
| Backend-Tests (Multi-Tenant, Auth, Module, Sicherheit) | ✅ 62 Testdateien, 837 Tests (Coverage 94 %) | — | — |
| Dashboard | ✅ | ✅ DashboardView | — |
| Einkauf 2.0 (Multi-Listen, Stores) | ✅ | ✅ ShoppingView | ✅ Socket |
| Aufgaben 2.0 (Unified Tasks) | ✅ | ✅ TodosView | ✅ Socket |
| Finanzen 2.0 (Budget + Bills) | ✅ | ✅ ExpensesView | ✅ Socket |
| Kalender + Events | ✅ | ✅ CalendarView | ✅ Socket |
| Abstimmungen (Polls) | ✅ | ✅ (integriert in Calendar/Food) | ✅ Socket |
| Haustiere (Katzen) | ✅ | ✅ PetsView + PetDetailView | — |
| Pflanzen (Pflegeaufgaben, Pflege-Log, Foto, Web Push, Dashboard-Kachel) | ✅ | ✅ PlantsView + PlantDetailView | ✅ Socket |
| Pflanzen: KI-Pflegehinweise (Vorschlag prüfen, Aufgaben/Hinweise übernehmen; nur mit Server-Schlüssel + Haushalts-Opt-in) | ✅ `POST /ai/plant-care` (unverändert) | ✅ `AiPlantCareCard` im Anlegen-Dialog und in PlantDetailView | — |
| Essen (Wochenmenü + Rezepte) | ✅ | ✅ FoodView | — |
| Notizen | ✅ | ✅ NotesView | — |
| App-Shell (Bottom-Nav, MoreSheet, Sync-Status) | — | ✅ | — |
| PWA (installierbar, Service Worker) | — | ✅ | — |
| Web Push (Todo-Erinnerungen, Tier-/Pflanzenpflege, Putzplan „Du bist dran“, Dokument-Ablauf) | ✅ | ✅ | — |
| Zahl am App-Icon (Badging API; iOS ab 16.4 als installierte App mit erlaubten Benachrichtigungen) | ✅ | ✅ | Socket |
| Homescreen-Widget über Scriptable (iPhone) mit Nur-Lese-Schlüssel | ✅ | ✅ | — |
| Foto-Upload verkleinert im Browser (1600 px, HEIC → JPEG), nutzt bei fehlendem HEIC-Decoder den Serverfallback und nennt den Fehlergrund | ✅ | ✅ | — |
| Dokument-Ablage (Verträge, Rechnungen, Garantien; mehrseitig, Vorschau, Speicher-Limit) | ✅ | ✅ DocumentsView | ✅ Socket |
| Auth-Härtung (Rate-Limits, Refresh-Rotation, Security-Header/CSP) | ✅ | — | — |
| Refresh-Token als HttpOnly-Cookie (H-01: `casa_rt`, CSRF-Header `X-Requested-With: casa`, Migration alter `localStorage`-Tokens) | ✅ | ✅ Auth-Store, API-Client, Cross-Tab über Sitzungs-Marker | — |
| Socket-Sitzungen enden mit Token-Ablauf und Logout | ✅ Ablauf-Timer, `reauth`, Trennen bei Logout | ✅ Token-Übergabe nach Refresh, Auto-Reconnect | ✅ |
| Offline-Basis M0 (Client-IDs, `version`/`updated_at`) | ✅ Shopping, Todos, Chore-Zuweisungen | ✅ Stores | ✅ veraltete Events werden verworfen |
| CI (Lint, Tests mit Coverage, Dependency-Audit) | — | — | — |
| Tags (NFC-Chips/QR-Sticker, Ein-Tipp-Aktionen inkl. Pflanze gießen / Pflegeaufgabe) | ✅ Registry, CRUD, resolve/execute | ✅ TagsView, Scan-Seite `/t/:token`, QR, Web NFC | ✅ Socket |
| Produktions-Deployment (Docker, Nginx Proxy Manager) | ✅ | ✅ | — |
| KI-Assistent (optional): Rezeptvorschlag aus Zutaten, Pflanzenpflege-Hinweise; Opt-in pro Haushalt, Tageslimit pro Haushalt und pro Person | ✅ `routers/ai.py`, `services/ai/` | ✅ Karte in FoodView, `/assistant`, Einstellungen | ✅ `household_updated` (Opt-in) |
| Rezepte mit Zubereitungsschritten und Tags | ✅ | ✅ Anzeige in den Rezept-Details | ✅ Socket |

### ❌ Offen (nächste Schritte)

| Feature | Aufwand | Prio | Beschreibung |
|---|---|---|---|
| Offline-Betrieb ab M1 | Gross | 🔵 Niedrig | IndexedDB, Änderungs-Warteschlange, Synchronisation; Plan und Etappen in `docs/offline-first-phase2.md`. Vorher offen: Entscheidung E8 (nur kürzlich abgehakte Einkäufe synchronisieren oder Funktion „Abgehakte löschen“) |
| Dokumente verknüpfen | Mittel | 🔵 Niedrig | Verknüpfung mit Ausgaben/Terminen (Datenmodell ist vorbereitet, eigene Link-Tabelle) |
| Einladungscode nur für Admins sichtbar? | Klein | 🔵 Niedrig | Offene Produktfrage zu H-12: Der Code ist weiterhin für alle Mitglieder sichtbar (Ablauf und Rotation sind umgesetzt) |
| „Überall abmelden“ | Klein | 🔵 Niedrig | Es gibt keinen Endpunkt, der alle Refresh-Tokens eines Users revoked; das passiert heute nur über die Reuse-Erkennung. Nützlich zusammen mit Passwort-Ändern |
| Frontend-Testabdeckung | Mittel | 🟡 Mittel | 77,49 % Statements, 72,14 % Branches (Statement-Schwelle 66 % in `vitest.config.ts`, CI bricht darunter ab); Komponenten, Stores `polls`/`dashboard` und die Repositories sind ungetestet; Schwelle bei Verbesserung nachziehen |
| FR/IT-Sprachen | Klein | 🔵 Niedrig | Locale-Erweiterung |
| Chores-Statistiken | Klein | 🔵 Niedrig | „Wer hat wie oft geputzt“ |
| KI-Assistent Etappe 2 | Mittel | 🔵 Niedrig | Beleg-Scan per Foto (Ausgabe vorbefüllen), Wochenplan-Vorschlag; Plan in `docs/ai-assistant.md` |
| Rezepte im Frontend anlegen/bearbeiten | Mittel | 🔵 Niedrig | Es gibt keine Rezept-Verwaltung in der Oberfläche; Rezepte entstehen bisher nur über die API bzw. den KI-Vorschlag |

---

## 8. Bekannte Einschränkungen

| Thema | Details | Prio |
|---|---|---|
| Wiederholtes Anlegen nach Löschen | Wird ein Anlegen wiederholt, nachdem jemand anderes den Eintrag gelöscht hat, taucht er wieder auf. Dafür bräuchte der Server Lösch-Vermerke (Tombstones); bewusst zurückgestellt | Phase 2 |
| `version`/`updated_at` nur teilweise | Vorhanden auf Einkaufslisten, Einkaufseinträgen, Todos und Putzplan-Zuweisungen; andere Entitäten haben sie nicht | Phase 2 |
| `navigator.onLine` unzuverlässig | Captive Portals und WLAN ohne Internet werden nicht erkannt | Phase 2 |
| Kalender-Migration (#9) | Termine, die der alte Fehler beim Bearbeiten bereits verschoben hatte, kann die Migration nicht erkennen; sie gelten als zuletzt gespeicherte Zeit und müssen ggf. von Hand korrigiert werden | Einmalig |
| PDF-Vorschau unter der CSP | Im eingebetteten PDF-Betrachter fehlen die Schaltflächen „Drucken“ und „Mehr“ (nicht durch Styles verursacht, nicht weiter untersucht); die App hat einen eigenen Download-Button. Die CSP wurde nur für `/documents` und `/shopping` im Browser geprüft | Gering |
| Bestehende wiederkehrende Rechnungen | Haben noch keinen Standard-Zahler; beim ersten Buchen wird im Dialog die aktuelle Person vorgeschlagen | Gering |
| Logout trennt Sockets aller Geräte | Der Access-Token trägt keine Geräte-Kennung; andere Geräte verbinden sich sofort selbst neu (kurzer Reconnect mit Nachladen). Ein gestohlenes Access-Token kann bis zu seinem Ablauf (15 Min.) weiter verbinden | Akzeptiert |
| Rate-Limits nur pro IP, im Speicher | Zähler gehen beim Neustart verloren; passt zu einem Worker (Socket.IO ohne Message-Queue) | Akzeptiert |
| Start ohne Netz | Der Access-Token wird nicht mehr persistiert; ohne Netz zeigt die App die Shell („offline eingeloggt“), hat aber keinen Token, bis der erste Request nach Rückkehr des Netzes ihn per Cookie-Refresh holt. Ohne Offline-Daten (M1) ist das gleichwertig zum früheren Verhalten | Phase 2 |
| Native Builds (Capacitor) | Der HttpOnly-Cookie setzt einen Browser voraus; ein nativer Client müsste die Body-Variante von `/refresh` (ohne `X-Requested-With`) mit SecureStorage nutzen — siehe H-01 im Hardening-Review | Später |
| KI-Assistent ohne echten API-Test | Entwickelt und getestet mit gemocktem Client und einem lokalen Fake des Messages-Endpunkts; es gab keinen Aufruf gegen die echte API (kein Schlüssel in der Entwicklungsumgebung). Token-Zahlen in `docs/ai-assistant.md` sind Schätzungen | Prüfen |
| KI-Tageslimit nach UTC-Tag | `ai_usage` zählt pro UTC-Tag, nicht nach der Zeitzone des Haushalts (Wechsel um 01:00/02:00 Uhr Schweizer Zeit) | Gering |
| Lange KI-Anfragen hinter Nginx Proxy Manager | Rezeptvorschläge können über 60 s dauern; `nginx.conf` erlaubt 200 s, NPM muss ggf. angepasst werden | Prüfen |
| Major-Updates ohne Gerätetest | Pillow 12, pillow-heif und cryptography 50 wurden über Tests und Stichproben geprüft; PNG/HEIC-Uploads auch lokal in Chromium und WebKit. Kein Test auf einem echten iPhone oder einer echten Web-Push-Zustellung auf einem Gerät | Prüfen |
| `deleteItem()` Rollback-Position | Bei paralleler Socket-Mutation kann die Position abweichen (kosmetisch) | Gering |
| UI-Audit: offene Punkte | Eigene Dialoge (`ExpenseFormDialog`, `BalanceSummary`) statt `BaseDialog`, nachgebaute Pill-Tabs in `ShoppingView`, Löschen als Text-Link in Pflanzen-/Tierkarten, Sync-Punkt „verbindet neu“ unter 3 : 1 — siehe `docs/design/ui-audit.md` | Gering |

---

## 9. Dependencies

### Backend (Python)
| Package | Version | Zweck |
|---|---|---|
| FastAPI | 0.141.1 | Web-Framework |
| SQLAlchemy | (via requirements.txt) | ORM |
| Alembic | 1.18.5 | DB-Migrationen (37 Versionen) |
| psycopg2-binary | 2.9.12 | PostgreSQL-Driver |
| python-socketio | (via requirements.txt) | WebSocket |
| bcrypt | 4.0.1 | Passwort-Hashing |
| pydantic | 2.13.4 | Validierung |
| PyJWT | 2.15.0 | JWT |
| Pillow | 12.3.0 | Bildverarbeitung (Uploads) |
| pillow-heif | 1.8.0 | HEIC/HEIF-Decoder als Pillow-Plugin für den Upload-Serverfallback |
| pywebpush | 2.5.0 | Web Push |
| anthropic | 1.11.0 | KI-Assistent (offizielles SDK, basiert auf `httpx2`) |
| pytest, httpx, pytest-cov, ruff | (nicht in `requirements.txt`) | Tests und Lint; werden in der CI separat installiert |

### Frontend (Node.js)
| Package | Version | Zweck |
|---|---|---|
| Vue | 3.5.43 | UI-Framework |
| Pinia | 4.0.2 | State Management |
| Vue Router | 5.2.0 | Routing |
| vue-i18n | (via package.json) | Internationalisierung |
| Axios | 1.20.0 | HTTP-Client |
| socket.io-client | 4.8.3 | WebSocket-Client |
| qrcode-generator | 2.0.4 | QR-Codes für Tags, clientseitig, ohne Abhängigkeiten |
| TypeScript | 5.8.3 | Typisierung |
| Vite | 8.2.0 | Build-Tool |

---

## 10. Abgeschlossene Epics

Die Nummerierung ist die der Dokumentation und nicht identisch mit den „Epic-N“-Angaben in einzelnen Commit-Meldungen (dort steht „Epic 11“ für den Connection-Pool-Fix, „Epic 12/12b“ für die Auth-Härtung, „Epic 13“ für Mobile-Eingaben und Vitest, „Epic 14“ für das Produktions-Deployment). Die Git-Historie ist in dieser Umgebung nur ab 2026-08-06 verfügbar (flacher Klon); Epics 1–6 und 8 lassen sich daher nur über den Code belegen. Die Epics 9–16 sind im Repository als Sammel-Commits vom 2026-08-08 eingegangen, die genannten Abschlussdaten stammen aus der früheren Fassung dieses Dokuments. Epic 20 und höher folgen der Git-Historie (Merge-Commits und direkte Commits auf `master`).

### Epic 1: UI/UX-Überarbeitung — Design-System + Mobile-First ✅
- **Abgeschlossen:** 05.08.2026
- **Umfang:** Design-Token-System, 5 Basis-Komponenten, App-Shell mit Mobile Tab-Bar + Desktop Top-Bar, alle Views migriert
- **Review:** UI-Polish-Review durchlaufen, 13 Findings behoben
- **Details:** die frühere Detailliste ist nicht mehr im Repository (`.zoocode/todo.md` beschreibt inzwischen die Docker-Produktion, Epic 22)

### Epic 2: Todo-Frontend + Household-Beitritt ✅
- **Abgeschlossen:** 05.08.2026
- **Umfang:** TodosView + TodoList (556 Zeilen), HouseholdView mit Join/Invite/Members, Backend Join-Endpoint + Tests
- **Tests:** 5 Backend-Testdateien (Auth-Guard, Shopping-Scoping, Todo-Scoping, Household-Join)

### Epic 3: Expenses-Modul (Ausgaben-Teilung) ✅
- **Abgeschlossen:** 05.08.2026
- **Schritt 1: Datenmodell + Migration** ✅
  - `Expense` + `ExpenseShare` Models, Alembic-Migration `61637c8c98fb`, Rappen-Integer-Konvention
- **Schritt 2: CRUD-API + Split-Logik** ✅
  - Pydantic-Schemas (inline), Service-Funktionen (`split_evenly`, `validate_custom_shares`, `assert_users_in_household`)
  - 4 REST-Endpunkte (GET/POST/PATCH/DELETE), even/custom Split, 44 Tests gesamt (21 neue)
- **Schritt 3: Saldo-Endpoint + Settlement** ✅
  - `GET /balances` mit SQL-Aggregation, `compute_settlements()` Greedy-Algorithmus
  - `BalancesResponse` (balances + settlements + unassigned_rappen), 56 Tests gesamt (12 neue)
- **Schritt 4: Socket.IO-Events** ✅
  - `expense_created/updated/deleted` Events, identisches Pattern wie Shopping/Todos
  - Kein `balances_updated`-Event (Frontend refetcht stattdessen), 61 Tests gesamt (5 neue)
- **Schritt 5a: Frontend-Datenschicht** ✅
  - Types, Repository, Pinia Store (Composition API), Socket-Handler in App.vue, Money-Helper
  - `vue-tsc --noEmit` erfolgreich, kein Optimistic-Update bei Create (serverseitiger Split)
- **Schritt 5b: Vue-Views + Routing** ✅
  - ExpensesView, ExpenseList, BalanceSummary, ExpenseFormDialog
  - Route `/expenses`, Navigation (4 Tabs), Members im Expenses-Store
  - Even/Custom-Split UI, Betragsvalidierung via `parseAmountToRappen`, Optimistic Delete

### Epic 4: Settlements (Ausgleichszahlungen) ✅
- **Abgeschlossen:** 2026-08-05
- **Umfang:** Settlement-Model + CRUD-API (3 Endpoints) + Frontend (Store, Repository, Inline-Erfassung in BalanceSummary)
- **Tests:** test_settlements.py (23 Tests, Scoping + CRUD + Events + Balance-Integration)

### Epic 5: i18n (Internationalisierung DE/EN) ✅
- **Abgeschlossen:** 2026-08-06
- **Umfang:** vue-i18n, detectLocale (localStorage → navigator.language → en), 255 Keys in de.json + en.json
- **Build-Absicherung:** `check-locales.js` prüft Key-Sync, in Build-Pipeline integriert
- **Error-Codes:** Maschinenlesbare Codes (backend) → i18n-Keys (frontend)

### Epic 6: Chores-Modul (Putzplan mit Ämtli-Rotation) ✅
- **Abgeschlossen:** 2026-08-06
- **Design-Entscheidungen:**
  - Kalender-basierte Rotation (nicht erledigungsbasiert)
  - Lazy-Materialisierung (kein Cron/Background-Job)
  - Household-Zeitzone (Default: Europe/Zurich)
  - Recurrence: weekly/biweekly/monthly (bewusst simpel)
- **Backend:**
  - Models: Chore, ChoreAssignment, Household.timezone
  - Service: `chore_scheduler.py` (Datumsberechnung, Rotation, Materialisierung mit Savepoint-Safety)
  - API: 8 Endpoints (CRUD Chores + 4 Assignment-Endpoints)
  - Migration: `d5f2a8e3b7c1` (+ Postgres Enum-Fix)
- **Frontend:**
  - ChoresView.vue: "Diese Woche" (Assignments gruppiert nach Tag) + "Ämtli verwalten" (CRUD)
  - Store mit Optimistic Updates, Toggle-Mutex, 5 Socket-Handler
  - Route /chores, 🧹-Tab in Navigation (5 Module)
- **Tests:** 36 neue Tests (28 API/Scheduler + 8 Scoping), Gesamt: 118

### Epic 7: Household-Management + Rollen + Währung ✅
- **Abgeschlossen:** 2026-08-06
- **Umfang:**
  - Household CRUD: Erstellen (POST), Umbenennen (PATCH), Verlassen (POST /leave), Mitglied entfernen (DELETE)
  - Rollen-System: admin/member, verify_household_admin Dependency, Auto-Promotion bei Admin-Abgang
  - Währung: Household.currency (Default CHF), CURRENCY_MISMATCH-Validierung
  - Registrierung: household_name ODER invite_code (XOR-Validierung)
  - Invite-Code-Service: Gemeinsame Generierung mit Retry-Logik
  - Frontend: NoHouseholdView, BaseDialog, überarbeitete RegisterView (Tab-Umschalter), HouseholdView (4 Sektionen)
  - Socket-Events: household_updated, household_member_joined/left/removed
  - 4 neue Socket-Handler im Auth-Store
- **Tests:** 5 neue Testdateien (test_currency, test_admin_guard, test_households, test_leave_remove, test_register), ~33 neue Tests, Gesamt: ~151
- **Migration:** `a194489b8f0e` (add_household_currency)
- **i18n:** 205 → 255 Keys (50 neue Keys für Household-Management, Rollen, Währung)

### Epic 8: Design-Foundation Teil 3 — UI auf Design-System bringen ✅
- **Abgeschlossen:** 2026-08-07
- **Scope:** Rein visuell, kein Backend, keine Funktionsänderungen
- **Design-System-Umsetzung:**
  - Theme-Tokens: Neue Radii (`--radius-card: 20px`, `--radius-btn: 12px`, `--radius-dialog: 24px`)
  - 7 UI-Komponenten auf neue Tokens umgestellt (card, acc, chip, line-strong, ink, sub statt veralteter neutral-Aliases)
  - Buttons: Primary=`var(--acc)`, Secondary=`var(--chip)`, Ghost=`var(--acc)`/`var(--acc-soft)`
  - Karten: radius 20px, Dialoge: radius 24px, Inputs/Buttons: radius 12px
  - Abschnittstitel: `font-family: var(--font-display)` (Quicksand 600)
- **Neue Komponenten:**
  - `BaseCheckCircle.vue`: Runde Checkbox (ok-grün + weisser PhCheck bold), ersetzt native Checkboxen
  - `BasePillTabs.vue`: Generische Pill-Filterleiste (aktiv=ink/card, inaktiv=chip/ink)
  - `utils/memberColor.ts`: Deterministisches User→Farbe-Mapping (6 Farben)
- **Icon-Migration:** Lucide → Phosphor (`@phosphor-icons/vue`), 26 Icons in 16 Dateien migriert, `lucide-vue-next` entfernt
- **Integrationen:**
  - BaseCheckCircle in ShoppingList + TodoList (erledigte Items: line-through + var(--sub))
  - BasePillTabs in ChoresView (ersetzt showOnlyMine Toggle)
- **Validierung:** typecheck ✅, build ✅, 272 i18n-Keys sync ✅
- **i18n:** 255 → 272 Keys (17 neue Keys für PillTabs-Labels, Chores-Filter)

### Epic 9: Dashboard ✅
- **Abgeschlossen:** 2026-08-07
- **Umfang:** Dashboard-View mit Tagesgruss, Schnellzugriff-Buttons (Shopping, Task, Expense), Widget-Übersicht (Aufgaben, Einkauf, Finanzen)
- **Backend:** `app/routers/dashboard.py` – aggregierter Dashboard-Endpunkt
- **Frontend:** DashboardView.vue, `stores/dashboard.ts`, `repositories/dashboardRepository.ts`
- **Tests:** `test_dashboard_scoping.py` (Multi-Tenant-Scoping)
- **i18n:** `dashboard.*` Keys (15+ Keys: greetings, widgets, quick-actions)
- **Navigation:** Dashboard als Startseite (`/` → `/dashboard`)

### Epic 10: Einkauf 2.0 – Multi-Listen + Stores ✅
- **Abgeschlossen:** 2026-08-07
- **Umfang:** ShoppingList-Model (Multiple Listen pro Haushalt), Gruppen nach Geschäft/Kategorie, Zuweisung zu Mitgliedern, Artikel-Detailansicht
- **Backend:** `ShoppingList` Model, `app/routers/shopping.py` (list_router + router), Socket-Events `shopping_list_created/updated/deleted`
- **Migration:** `e8f4b2a6c9d3` (add_shopping_lists), `0f34ff355756` (add_ondelete_to_shopping_items_fks)
- **Frontend:** ShoppingView.vue überarbeitet (Listen-Tabs, Gruppen-Toggle, Artikeldetails), `stores/shopping.ts` erweitert
- **Hinweis:** Der Gruppen-Umschalter (Geschäft/Kategorie) ist seit Epic 19 nicht mehr in der Oberfläche; die i18n-Schlüssel `shopping.groupByStore`/`shopping.groupByCategory` sind nur noch in den Sprachdateien vorhanden
- **i18n:** `shopping.lists`, `shopping.newList`, `shopping.groupByStore`, `shopping.groupByCategory`, `shopping.storePlaceholder`, `shopping.assignToMe` etc.

### Epic 11: Aufgaben 2.0 – Unified Tasks ✅
- **Abgeschlossen:** 2026-08-07
- **Umfang:** Aufgaben-View vereinigt Todos + Chore-Assignments in einer Timeline-Ansicht (Überfällig / Heute / Diese Woche / Später). Todo-Tags, Todo-Claim, Personen-Filter (PillTabs)
- **Backend:** `app/routers/tasks.py` – Unified Tasks Endpoint (merges todos + chore assignments), `Todo.tags` JSON-Feld, Claim-Endpoint (2026-10: entfernt — nicht genutzt, PD-C2)
- **Migration:** `e6cbf2921e48` (add_tags_to_todos)
- **Frontend:** `TodosView.vue` (komplett neu als Unified Tasks), `stores/tasks.ts`, `repositories/tasksRepository.ts`, UnifiedTask-Type
- **Tests:** `test_todo_tags.py`, `test_todo_claim.py`
- **i18n:** `tasks.*` Keys (filterAll, filterShared, groupOverdue/Today/ThisWeek/Later, claim, recurring, manageChores)

### Epic 12: Finanzen 2.0 – Budget + Wiederkehrende Rechnungen ✅
- **Abgeschlossen:** 2026-08-07
- **Umfang:** Budget pro Monat, wiederkehrende Rechnungen (RecurringBill), Rechnungs-Buchung als Expense, Finanz-Übersicht mit Budget-Balken
- **Backend:** `Budget` + `RecurringBill` Models, `app/routers/budgets.py`, `app/routers/recurring_bills.py`, Finanz-Summary-Endpoint
- **Migration:** `f1a2b3c4d5e6` (add_finance_v2_models)
- **Frontend:** ExpensesView.vue überarbeitet (Budget-Widget, Pending Bills, Recent Expenses, Bill-Management), `stores/finance.ts`, `repositories/financeRepository.ts`
- **Tests:** `test_budget_scoping.py`, `test_recurring_bill_scoping.py`, `test_recurring_bill_book.py`, `test_finance_summary.py`
- **i18n:** `finance.*` Keys (available, budgetLine, noBudget, setBudget, pendingBills, recurringBills, addBill etc.)
- **Socket-Events:** `budget_updated`, `recurring_bill_created/updated/deleted/booked`

### Epic 13: Kalender + Polls ✅
- **Abgeschlossen:** 2026-08-07
- **Umfang:** Event-Kalender (Wochenansicht + Liste), Event-CRUD, Ganztägige Events, Abstimmungen (EventPoll) mit Vote + Entscheidung → Event-Erstellung
- **Backend:** `Event`, `EventPoll`, `EventPollOption`, `EventPollVote` Models, `app/routers/events.py`, `app/routers/polls.py`
- **Migration:** `4678310121c3` (add_events_table), `d155cbf3f424` (add_event_polls), `k5l6m7n8o9p0` (add_poll_type_and_recipe_id)
- **Frontend:** CalendarView.vue (Wochen- und Listenansicht), `stores/calendar.ts`, `stores/polls.ts`, `repositories/calendarRepository.ts`, `repositories/pollsRepository.ts`, `utils/categoryColors.ts`
- **Hinweis:** Die ursprünglichen festen Termin-Kategorien (arbeit, katzen, haushalt, …) gibt es nicht mehr; `Event` hat keine Kategorie, sondern gehört zu einem Kalender (Epic 20). `utils/categoryColors.ts` enthält nur noch die Standard-Farbpalette für neue Kalender.
- **Tests:** `test_event_scoping.py`, `test_poll_scoping.py`
- **i18n:** `calendar.*` Keys (25+ Keys), `polls.*` Keys (18+ Keys)
- **Socket-Events:** `event_created/updated/deleted`, `poll_created/voted/decided/deleted`

### Epic 14: Haustiere (Katzen) ✅
- **Abgeschlossen:** 2026-08-07
- **Umfang:** Pet-Management (Name, Rasse, Geburtsdatum, Gewicht, Foto-URL), Fütterungs-Log (Morgen/Abend pro Tag), Medikamente-Management + Verabreichungs-Log, Detail-Profil-Seite (Chip-Nr, Versicherung, Tierarzt, Futter-Notizen, Gesundheitseinträge mit Ampel-System)
- **Backend:** `Pet`, `FeedingLog`, `Medication`, `MedicationLog` Models, `app/routers/pets.py`
- **Migration:** `g1h2i3j4k5l6` (add_pets_and_feeding_logs), `h2i3j4k5l6m7` (add_medications_module), `i3j4k5l6m7n8` (add_pet_profile_fields)
- **Frontend:** PetsView.vue (Übersicht mit Fütterungs-Widget), PetDetailView.vue (Profil, Medikamente, Gesundheitseinträge), `stores/pets.ts`, `repositories/petsRepository.ts`
- **Tests:** `test_pet_scoping.py`, `test_feeding_scoping.py`, `test_medication_scoping.py`
- **i18n:** `pets.*` Keys (50+ Keys inkl. Medikamente, Gesundheit, Profil)

### Epic 15: Essen (Wochenmenü + Rezepte) ✅
- **Abgeschlossen:** 2026-08-08
- **Umfang:** Rezept-Verwaltung (Name, Portionen, Kosten, Dauer, Zutaten-Liste, Favoriten), Wochenmenü-Planung (Rezept oder Freitext pro Tag), "Fehlende Zutaten zur Einkaufsliste"-Button, Essens-Abstimmung (poll_type='meal')
- **Backend:** `Recipe`, `MealPlanEntry` Models, `app/routers/food.py` (recipe_router + meal_plan_router)
- **Migration:** `j4k5l6m7n8o9` (add_food_module)
- **Frontend:** FoodView.vue (Wochenmenü, Rezept-CRUD, Meal-Polls), `stores/food.ts`, `repositories/foodRepository.ts`
- **Tests:** `test_food_scoping.py`, `test_food_shopping.py`, `test_meal_poll.py`
- **i18n:** `food.*` Keys (35+ Keys)
- **Security-Review:** `docs/security-review-food-module.md`, `docs/security/food-module-review.md`

### Epic 16: Notizen ✅
- **Abgeschlossen:** 2026-08-08
- **Umfang:** Notiz-CRUD (Titel, Body, Tag, Pinned), Angepinnte Notizen oben, Tag-Filter
- **Backend:** `Note` Model, `app/routers/notes.py`
- **Migration:** `l6m7n8o9p0q1` (add_notes_module), `m7n8o9p0q1r2` (add_ondelete_set_null_notes)
- **Frontend:** NotesView.vue, `stores/notes.ts`, `repositories/notesRepository.ts`
- **Tests:** `test_note_scoping.py`
- **i18n:** `notes.*` Keys (15 Keys)

### Epic 17: Feinschliff 0d – App-Shell, Navigation, UI-Polish ✅
- **Abgeschlossen:** 2026-08-08
- **Umfang:**
  - Mobile Bottom-Nav vereinfacht auf 4 Tabs + "Mehr"-Sheet (Start, Kalender, Aufgaben, Einkauf, Mehr)
  - MoreSheet-Komponente: Overlay-Bottom-Sheet mit 5 Einträgen (Finanzen, Katzen, Essen, Notizen, Einstellungen); inzwischen 6 Einträge, seit Epic 25 zusätzlich „Dokumente“
  - Desktop Top-Bar: 6 direkte Nav-Links (Start, Kalender, Einkauf, Aufgaben, Finanzen, Haushalt) — Putzplan-Link entfernt, stattdessen "Ämtli verwalten"-Link in der Aufgaben-View
  - Sync-Status-Indikator (grün/gelb/grau) in Bottom-Nav und Top-Bar
  - BaseAvatar-Komponente mit deterministic User→Farbe-Mapping
  - PageHeader-Komponente für konsistente Seitenkopfzeilen
  - `useTheme` Composable
  - `utils/dates.ts` – formatDateShort Helper
- **Frontend:** TheBottomNav.vue, MoreSheet.vue, BaseAvatar.vue, PageHeader.vue, `composables/useTheme.ts`, `utils/dates.ts`
- **i18n:** `nav.*`, `moreSheet.*`, `sync.*` Keys
- **Navigation-Konsolidierung:** `/chores` aus Desktop-Top-Bar entfernt, "Ämtli verwalten"-Link (PhBroom) in TodosView ergänzt (`tasks.manageChores` Key)

### Epic 18: Upload-Infrastruktur + Katzenfotos ✅
- **Abgeschlossen:** 2026-08-10
- **Umfang:**
  - Wiederverwendbare Datei-Upload-Infrastruktur (lokal, später Supabase-Adapter)
  - StoredFile Model + LocalStorageService (data/uploads/{household_id}/{uuid}{ext})
  - Files Router: POST (Upload + Pillow-Resize auf 1600px), GET (JWT-geschützter Download), DELETE (mit FILE_IN_USE-Schutz)
  - Pet-Foto-Integration: PATCH pet mit photo_file_id, Validierung Household+MIME
  - Frontend: JWT-geschützter Blob-Download via ObjectURL, useProtectedImage Composable
  - PetPhotoAvatar Component (sm/md/lg), Upload-Flow in PetDetailView, Thumbnails in PetsView
  - Docker: uploaddata Volume für Persistenz
  - Security-Härtung: Chunk-basiertes Lesen, MAX_IMAGE_PIXELS, PDF Magic-Byte, EXIF-Rotation, Path-Traversal-Defense, Content-Disposition-Sanitisierung
- **Backend:** `routers/files.py`, `services/storage.py`, `models.py` (StoredFile), `routers/pets.py` (photo_file_id)
- **Frontend:** `repositories/filesRepository.ts`, `composables/useProtectedImage.ts`, `components/PetPhotoAvatar.vue`, PetDetailView, PetsView
- **Tests:** 14 neue Tests in `test_files_scoping.py` (Cross-Tenant, Validation, Upload/Download/Delete)
- **Reviews:** Security-Review (`docs/security/epic8-upload-review.md`), Business-Logic-Review (`docs/review-epic8-upload.md`)
- **i18n:** 9 neue Keys (pets.photo*, files.*) → 588 Keys total

### Epic 19: Einkaufsliste „nach Geschäft" (Redesign + Verwaltung) ✅
- **Abgeschlossen:** 2026-08-12
- **Umfang:**
  - Geschäft als primäres Ordnungskonzept (ersetzt Abteilung/Geschäft-Tabs)
  - Store-Chips-Filter oberhalb der Liste (Alle + je Geschäft mit Badge-Counter)
  - Quick-Add übernimmt automatisch aktiven Store-Filter
  - Item-Edit-Sheet (Bottom-Sheet): Name, Menge, Geschäft (Chips + Freitext), Abteilung
  - Store-Verwaltung: Umbenennen und Auflösen via Gruppen-Header Kebab-Menü
  - Merge-Warnung wenn Ziel-Store bereits existiert
  - Echtzeit-Sync: `shopping_items_bulk_updated` Socket-Event
  - Keine neue DB-Tabelle, keine Migration (Stores bleiben abgeleitete Freitext-Werte)
- **Backend:** 2 neue Endpoints in `routers/shopping.py`: `GET /stores` (distinct), `POST /reassign-store` (Bulk-Update)
- **Frontend:** `ShoppingList.vue` (Hauptumbau), `ShoppingItemEditSheet.vue` (neu), `stores/shopping.ts`, `repositories/shoppingRepository.ts`, `App.vue` (Socket-Registrierung)
- **Tests:** 9 neue Tests in `test_shopping_stores.py` (GET stores, reassign rename/dissolve, cross-tenant, edge cases)
- **Reviews:** Security-Review (`docs/security/epic18-shopping-stores-review.md` — bestanden), Business-Logic-Review (2 Findings behoben: Merge-Warnung + maxlength)
- **i18n:** 15 neue Keys (shopping.allStores, renameStore, dissolveStore, editItem etc.) → 615 Keys total
- **Erledigt (Follow-up):** Case-insensitive Store-Normalisierung ✅
  - Backend (`routers/shopping.py`): Store-Werte werden bei Create/Update/Reassign normalisiert (trim, Mehrfach-Whitespace, leer → `null`); existiert im Haushalt bereits ein Store, der sich nur in Gross-/Kleinschreibung unterscheidet, wird dessen Schreibweise übernommen (kanonisch = häufigste Schreibweise, Tie-Break alphabetisch)
  - `GET /stores` liefert case-insensitive distinct (eine kanonische Schreibweise pro Gruppe); `POST /reassign-store` matcht die Quelle case-insensitive und merged in eine bestehende Ziel-Schreibweise — `ReassignStoreResponse` enthält neu `to_store` (tatsächlich verwendeter Ziel-Name)
  - Vergleich läuft Python-seitig (`str.lower`) statt per SQL `lower()`, damit SQLite (Tests) und PostgreSQL (Prod) identisch arbeiten (SQLite kennt `lower()` nur für ASCII); keine Migration, keine neue Tabelle
  - Frontend: `utils/storeName.ts` (`normalizeStoreName`, `storesEqual`, `findCanonicalStore`) — Chip-Filter, Gruppierung, Edit-Sheet-Chips und Merge-Warnung vergleichen case-insensitive; `reassignStore` übernimmt `to_store` aus der Response
  - Tests: +14 Backend-Tests in `test_shopping_stores.py` (Normalisierung Create/Update, case-insensitive distinct, Reassign mit abweichender Schreibweise, Merge, Cross-Tenant), +6 Vitest-Tests in `utils/__tests__/storeName.test.ts`

### Epic 20: Kalender-Verwaltung + Monatsansicht ✅
- **Abgeschlossen:** 2026-08-10 (Monatsansicht 2026-08-12)
- **Umfang:** Eigene Kalender (Name, Farbe, Position) ersetzen die festen Termin-Kategorien; Termine und Abstimmungen gehören zu einem Kalender. Monatsraster mit Tagesdetails und Avatar-Stapel neben Wochen- und Listenansicht
- **Backend:** `Calendar` Model, `app/routers/calendars.py` (4 Endpoints), Anpassungen in `events.py`, `polls.py`, `dashboard.py`; Socket-Events `calendar_created/updated/deleted`
- **Migration:** `p1q2r3s4t5u6` (add_calendars_replace_category)
- **Frontend:** Kalender-Verwaltung und Monatsraster in `CalendarView.vue`, `components/CalendarMonthGrid.vue`, `stores/calendar.ts`
- **Tests:** `test_calendar_scoping.py`
- **Reviews:** `docs/review-epic5-calendars.md`, `docs/security/epic5-calendars-review.md`, `docs/review-epic16-month-view.md`

### Epic 21: Todo-Erinnerungen + Tierpflege-Aufgaben ✅
- **Abgeschlossen:** 2026-08-10
- **Umfang:** Bis zu 5 Erinnerungen pro Todo; wiederkehrende Pflegeaufgaben pro Haustier (Intervall in Tagen, nächste Fälligkeit, „Erledigt“)
- **Backend:** `TodoReminder` und `PetCareTask` Models, Endpoints in `routers/todos.py` (2) und `routers/pets.py` (5), Socket-Events `pet_care_task_created/updated/deleted` (Erinnerungen laufen über `todo_updated`)
- **Migration:** `n1o2p3q4r5s6` (add_pet_care_tasks), `o1p2q3r4s5t6` (add_todo_reminders)
- **Frontend:** `TodoList.vue` (Erinnerungen), `PetDetailView.vue` (Pflegeaufgaben), `stores/todos.ts`, `stores/pets.ts`, Repositories
- **Tests:** `test_todo_reminders.py`, `test_pet_care_scoping.py`
- **Reviews:** `docs/review-todo-reminders.md`, `docs/security/todo-reminders-review.md`
- **Benachrichtigung:** Zustellung per Web Push, siehe Epic 24

### Epic 22: Docker-Deployment ✅
- **Abgeschlossen:** Entwicklungs-Setup 2026-08-08; Produktion hinter Nginx Proxy Manager 2026-08-25 (PR #3)
- **Umfang:** Multi-Stage-Images und Compose-Orchestrierung (Postgres, Backend, Frontend/Nginx), Windows-Server-Anleitung, Produktions-Compose ohne veröffentlichte Ports mit Healthchecks, `FRONTEND_PORT`, Non-root-Backend, Health-Endpoint mit DB-Check, Backup-/Restore-Skripte, `API_BASE` für same-origin-Betrieb
- **Dateien:** `docker-compose.yml`, `docker-compose.prod.yml`, `.env.example`, `.env.prod.example`, `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`, `scripts/backup-db.ps1`, `scripts/restore-db.ps1`
- **Tests:** `test_rate_limit_proxy.py`
- **Doku:** `docs/deployment.md`, `docs/DEPLOYMENT-WINDOWS-SERVER.md`, `.zoocode/todo.md`
- **Migrations-Fixes:** Postgres-Enum-Typen und `ondelete` in der Notizen-Migration (Commits 2026-08-08)

### Epic 23: Auth-Lebenszyklus (Refresh-Tokens) ✅
- **Abgeschlossen:** 2026-08-25 (PR #1 und #2)
- **Umfang:** Kurzlebiger Access-Token (15 Min.) plus rotierender Refresh-Token (30 Tage) mit Reuse-Erkennung und Kulanzfenster, Session-Persistenz im Frontend (`tokenStorage`), automatischer Refresh bei 401, Logout widerruft den Token, Rate-Limits und Transport-Robustheit
- **Backend:** `RefreshToken` Model, `POST /api/auth/refresh`, `POST /api/auth/logout`
- **Migration:** `r1s2t3u4v5w6` (add_refresh_tokens)
- **Frontend:** `services/tokenStorage.ts`, `api/client.ts` (Refresh-Interceptor), `stores/auth.ts`
- **Tests:** `test_auth_refresh.py`
- **Review:** `docs/security/epic12-auth-lifecycle-review.md`

### Epic 24: PWA + Web Push ✅
- **Abgeschlossen:** 2026-09-29 (PR #5)
- **Umfang:** Installierbare PWA (Manifest, Icons, Service Worker mit Hinweis auf neue Version); Web Push für Todo-Erinnerungen und Tierpflege-Aufgaben mit Scheduler im Backend, Geräte-Verwaltung in den Haushalt-Einstellungen
- **Backend:** `PushSubscription` Model, `routers/push.py` (4 Endpoints), `services/push_service.py`, `scripts/generate_vapid_keys.py`
- **Migration:** `s1t2u3v4w5x6` (add_push_subscriptions)
- **Frontend:** `pwa.ts`, `public/push-sw.js`, `services/pushService.ts`, `components/PushSettings.vue`, `repositories/pushRepository.ts`
- **Tests:** `test_push.py`
- **Offen:** Push für Chores und Ablaufdaten von Dokumenten (siehe Abschnitt 7)

### Epic 25: Dokument-Ablage ✅
- **Abgeschlossen:** 2026-10-06 (PR #7)
- **Umfang:** Verträge, Rechnungen und Garantien ablegen: Kategorien, Dokumentdatum, Ablaufdatum, Suche, mehrseitige Dokumente (bis 30 Dateien, Seiten umsortieren), Vorschau, Speicher-Limit pro Haushalt; schliesst die Upload-Befunde F-02 bis F-04
- **Backend:** `Document` und `DocumentFile` Models, `routers/documents.py` (10 Endpoints), `services/file_cleanup.py` (periodisches Aufräumen verwaister Uploads), Socket-Events `document_created/updated/deleted`
- **Migration:** `t1u2v3w4x5y6` (add_documents_module)
- **Frontend:** `DocumentsView.vue`, `stores/documents.ts`, `repositories/documentsRepository.ts`, `utils/documents.ts`; Eintrag „Dokumente“ im MoreSheet
- **Tests:** `test_documents.py`, `test_file_references.py`, `utils/__tests__/documents.test.ts`

### Epic 26: CI und Qualitätssicherung ✅
- **Abgeschlossen:** 2026-10-06 (PR #6, #15, #17, #19)
- **Umfang:** GitHub-Actions-Pipeline mit den Jobs `backend` (ruff, pytest mit Coverage), `frontend` (Locale-Check, Typecheck, Vitest mit Coverage) und `dependency-audit` (pip-audit, npm audit); Status-Badge in der README; Unit-Tests für Utils und die Stores Auth, Einkauf, Todos, Ämtli und Ausgaben; Store-Korrekturen (Geschäfts-Filter folgt dem Umbenennen, Rollback beim Löschen eines Ämtlis)
- **Dateien:** `.github/workflows/ci.yml`, `backend/pyproject.toml`, `frontend/vitest.config.ts`, `frontend/src/**/__tests__/`
- **Doku:** README und `docs/PROJECT-STATUS.md` neu geschrieben (PR #16, #19)

### Epic 27: Sicherheits- und Betriebs-Härtung ✅
- **Abgeschlossen:** 2026-10-06 (PR #8, #13, #14)
- **Umfang:** Rate-Limit-Umgehung per gefälschtem `X-Forwarded-For` behoben; HTTP-Security-Header und CSP, engeres CORS, Rate-Limits für Refresh/Logout/Beitritt; Pflicht-Secrets und lokal gebundene Ports in den Compose-Dateien; Backup inkl. Uploads; Abhängigkeits-Updates gegen bekannte Schwachstellen (u. a. Pillow 12, cryptography 50, PyJWT 2.15)
- **Dateien:** `backend/app/core/rate_limit.py`, `backend/app/core/security_headers.py`, `frontend/nginx/security-headers.conf`, `scripts/backup-db.ps1`
- **Tests:** `test_security_hardening.py`, `test_rate_limit_proxy.py`, `test_startup_config.py`
- **Review:** `docs/security/hardening-review.md`

### Epic 28: Datenkorrektheit, DB-Integrität, Mitglieder-Lebenszyklus ✅
- **Abgeschlossen:** 2026-10-06 (PR #9, #10, #11)
- **Umfang:** Ämtli-Rotation springt beim Umbenennen nicht mehr; Kalender-Uhrzeiten in der Haushalts-Zeitzone (inkl. Migration bestehender Termine); doppelte Teilnehmer bei Ausgaben abgelehnt; Ausgleich mit Ex-Mitgliedern; Standard-Zahler bei wiederkehrenden Rechnungen; Löschregeln (`ondelete`), eine Stimme pro Person und Abstimmung, eine Buchung pro Rechnung und Monat, `household_id`-Indizes; entfernte Mitglieder verlassen den Echtzeit-Raum, Einladungscode wird beim Entfernen erneuert (`POST …/invite-code/rotate`), Dateien werden beim Auflösen eines Haushalts entfernt
- **Migration:** `u1v2w3x4y5z6` (event_times_and_bill_payer), `v1w2x3y4z5a6` (integrity_constraints)
- **Services:** `event_times.py`, `household_checks.py`, `file_cleanup.py`
- **Tests:** `test_event_times.py`, `test_finance_correctness.py`, `test_db_integrity.py`, `test_member_lifecycle.py`

### Epic 29: Offline-first Meilenstein M0 ✅
- **Abgeschlossen:** 2026-10-06 (PR #12)
- **Umfang:** Konzeptdokument `docs/offline-first-phase2.md`; vom Client erzeugte IDs mit idempotentem Anlegen (Einkauf, Todos, Putzplan-Zuweisungen), `updated_at`/`version` auf vier Tabellen, Clients verwerfen veraltete Socket-Events. Weitere Meilensteine (IndexedDB, Warteschlange) sind offen
- **Migration:** `w1x2y3z4a5b6` (add_sync_version_fields)
- **Backend:** `SyncVersionMixin`, `services/client_ids.py`
- **Frontend:** `utils/syncVersion.ts`, versionierte Merges in den Stores
- **Tests:** `test_offline_sync.py`, `stores/__tests__/syncRaces.test.ts`, `utils/__tests__/syncVersion.test.ts`

### Epic 30: Stabilisierung August 2026 ✅
- **Abgeschlossen:** 2026-08-10 bis 2026-08-12 (direkte Commits)
- **Umfang:** Datenintegrität (Backup, Aufräumen von Dateien, Pfad-Prüfung), Connection-Pool und Event-Loop-Blocking behoben, Zahleneingaben ohne `type=number` (Text mit `inputmode`), Gewicht in kg mit robustem Parsing, Nginx-Upload-Limit, Vitest-Einführung mit Tests für `parseAmountToRappen`
- **Tests:** `test_pool_contention.py`, `utils/__tests__/money.test.ts`

### Epic 31: Pflanzen ✅
- **Abgeschlossen:** 2026-10-06
- **Umfang:**
  - Pflanzen pro Haushalt mit Name, Art (Freitext), Standort/Raum (Freitext), Notizen, Foto (bestehende Upload-Infrastruktur `StoredFile`, wie beim Tierfoto) und `care_notes` (Freitext-Pflegehinweise, Platzhalter für spätere KI-Pflegehinweise); kein Soft-Delete
  - Pflegeaufgaben (`PlantCareTask`): mehrere pro Pflanze; Pflegeart als fester Wert (`water`, `fertilize`, `repot`, `mist`, `other`, per CHECK-Constraint) plus optionalem Freitext-Label; Intervall in Tagen (Standard: gießen 7, düngen 30, umtopfen 365, besprühen 3, sonstiges 30); ohne Angabe ist die erste Fälligkeit „heute + Intervall"
  - Pflege-Log (`PlantCareLog`): wer hat wann welche Pflegeart erledigt, optional mit Notiz; „Erledigt" (`POST …/care-tasks/{id}/complete`) schreibt den Log-Eintrag und setzt die nächste Fälligkeit aus dem Intervall (Haushalts-Zeitzone); Log-Einträge überleben das Löschen der Aufgabe
  - `GET /plants/care-status` (analog `feeding-status`): alle Pflanzen mit nächster Fälligkeit pro Aufgabe und den Flags `due_today`/`overdue`; `POST /plants/water-all` (analog `feed-all`) erledigt alle fälligen Gießaufgaben des Haushalts
  - Foto: `PATCH` mit `photo_file_id`; `file_in_use`, Orphan-Cleanup und Pflanzenlöschung berücksichtigen Pflanzenfotos (eine Datei gehört höchstens einer Pflanze, einem Tier oder einem Dokument)
  - Socket-Events: `plant_created/updated/deleted`, `plant_care_logged` sowie `plant_care_task_created/updated/deleted`
  - Dashboard-Kachel „Pflanzen brauchen Wasser" (`plants_water`: Anzahl Pflanzen mit heute fälliger oder überfälliger Gießaufgabe, die fünf dringendsten)
  - Web Push: `process_plant_care_tasks` im Scheduler, ab 8:00 Haushaltszeit, einmalig pro Fälligkeit (`notified_at`), Text pro Locale, Link `/plants/{id}`
  - Frontend: `PlantsView` (Karten mit Fälligkeitsbadges überfällig/heute, Ein-Tipp „Gegossen", „Alle fälligen gießen"), `PlantDetailView` (Foto, Pflegearten, Pflege-Verlauf, Bearbeiten), Route `/plants` und `/plants/:id`, Eintrag im „Mehr"-Menü mit `PhPlant`
- **Backend:** `Plant`, `PlantCareTask`, `PlantCareLog` Models, `routers/plants.py`, `services/push_service.py`, `routers/dashboard.py`, `routers/files.py`
- **Migration:** `x1y2z3a4b5c6` (add_plants_module)
- **Frontend:** `stores/plants.ts`, `repositories/plantsRepository.ts`, `utils/plantCare.ts`, `components/PlantPhotoAvatar.vue`, `PlantsView.vue`, `PlantDetailView.vue`, `DashboardView.vue`, `App.vue` (Socket-Registrierung), `MoreSheet.vue`
- **Tests:** `test_plants.py` (31: CRUD, Cross-Household 403/404, Pflege-Log setzt Fälligkeit, Status-Endpunkt, `water-all`, Foto), +3 in `test_push.py`, +2 in `test_dashboard_scoping.py`; Frontend `stores/__tests__/plants.test.ts` (19) und `utils/__tests__/plantCare.test.ts` (4)
- **i18n:** `plants.*` (DE + EN), `nav.plants`, `moreSheet.plantsSub`, `dashboard.plantsWaterTitle`, Error-Codes `PLANT_NOT_FOUND`, `PLANT_CARE_TASK_NOT_FOUND` → 765 Keys total
- **Nicht enthalten:** NFC/QR-Tags und KI-Pflegehinweise (getrennte Vorhaben)

### Epic 32: Tags (NFC-Chips / QR-Sticker) ✅
- **Abgeschlossen:** 2026-10-06 (Branch `claude/nfc-qr-tags`)
- **Umfang:** Physische Tags, die beim Scannen eine Ein-Tipp-Aktion auslösen. Auf Chip bzw. QR-Code steht nur `https://<host>/t/<token>`; das Betriebssystem öffnet die URL in der installierten PWA (iOS kann Web NFC nicht, liest NFC-URLs aber nativ). Ziel und Aktion liegen in der Datenbank.
- **Aktionen (Registry `app/services/tag_actions.py`):** `pet.feed` (ein Tier oder alle; Slot nach Tageszeit, ab 14 Uhr Abend, auf der Bestätigungsseite umschaltbar), `pet.care_task.done`, `chore.assignment.done` (Zuweisung der laufenden Periode = jüngste bis heute seit `anchor_date`, erledigt oder nicht, sonst die nächste innerhalb von 6 Tagen; ist sie erledigt → „schon erledigt“, Rückstand und nächste Periode bleiben unangetastet), `shopping_list.open` (nur Navigation), `todo.done` (idempotent). Mutationen rufen die bestehenden Endpoint-Funktionen der Module auf (gleiche Validierung und Socket-Events). Keine Lösch-Aktionen. Ein neuer Zieltyp (z. B. `plant.water`) braucht nur einen Registry-Eintrag plus i18n-Keys; Anleitung im Modulkopf.
- **Geschäftsregeln:**
  - Anlegen, Ändern, Deaktivieren, Token neu erzeugen und Löschen nur für Admins; Liste und Ausführen für alle Mitglieder
  - Scan ohne Login → Login mit `redirect` zurück auf `/t/<token>`; die Aktion läuft erst nach Tipp auf der Bestätigungsseite (`*.open` navigiert direkt)
  - Unbekannter Token → 404, fremder Haushalt → 403 (auch bei deaktiviertem Tag), deaktiviert → 410 `TAG_DISABLED`, Ziel gelöscht → 404 `TAG_TARGET_NOT_FOUND`
  - Höchstens 200 Tags pro Haushalt; `use_count`/`last_used_at` zählen ausgeführte Aktionen und Aufrufe von Navigations-Tags
- **Backend:** `Tag`-Model, `app/routers/tags.py` (Verwaltung + Scan), `app/services/tag_actions.py`, `app/core/log_redaction.py` (Tokens in uvicorn-/slowapi-Logs geschwärzt)
- **Migration:** `b7c8d9e0f1a2` (add_tags)
- **Frontend:** `TagsView.vue` (`/tags`, Link unter Haushalt), `TagScanView.vue` (`/t/:token`), `stores/tags.ts`, `repositories/tagsRepository.ts`, `utils/tagScan.ts`, `utils/qr.ts` (`qrcode-generator`, SVG als `data:`-URL), `composables/useNfcWriter.ts` (Web NFC, `NDEFReader.write` mit URL-Record); Einkauf übernimmt `?list=<id>`
- **PWA/nginx:** Manifest-`shortcuts` (Einkauf, Aufgaben, Haustiere) und `launch_handler: navigate-existing`; `/t/*` bekommt die vorgecachte App-Shell (kein eigener Cache-Eintrag); nginx schwärzt Tokens in Pfad und Referer des Access-Logs
- **Tests:** `test_tags.py` (52 Tests: CRUD/Rollen, resolve/execute je Aktion, 403/404/410, Rate-Limit, Log-Schwärzung); Vitest `stores/__tests__/tags.test.ts`, `utils/__tests__/tagScan.test.ts` (+42); E2E mit headless Chromium gegen Produktions-Build und echte nginx-Konfiguration: 0 CSP-Verstösse
- **Security-Review:** `docs/security/tags-review.md`
- **i18n:** `tags.*` und `errors.TAG_*` (+121 Keys) → 821 Keys

### Epic 33: KI-Assistent — Etappe 1 (Rezeptvorschlag, Pflanzenpflege) ✅
- **Abgeschlossen:** 2026-10-06 (Branch `claude/ai-assistant`)
- **Umfang:**
  - Anbindung der Anthropic-API über das offizielle `anthropic`-SDK (1.11.0), Modell `claude-opus-5-5`; Tiefe über `output_config.effort` (Rezept `medium`, Pflege `low`), kein `thinking`-Parameter, kein Prefill, kein erzwungenes Tool
  - Strukturierte Ausgaben über `client.beta.messages.parse()` mit Pydantic-Modellen (JSON-Schema in `output_config.format`), kein Textparsing; Ausgabe wird in die Grenzen der App-Schemas gebracht
  - Serverseitige Fallbacks (`server-side-fallback-2026-07-01`, `fallbacks="default"`); `stop_reason == "refusal"` → 422 `AI_REFUSED`; typisierte SDK-Exceptions → 502/503 mit eigenen Codes; Timeout 90 s, `max_retries=1`, max. 4 gleichzeitige Aufrufe
  - Opt-in pro Haushalt (`households.ai_enabled`, Standard aus, nur Admins), Datenschutz-Hinweis in den Einstellungen; ohne `ANTHROPIC_API_KEY` meldet `GET /api/ai/status` `enabled: false` und das Frontend blendet alles aus
  - Kostenschutz: 10/min pro IP (slowapi), Tageslimit pro Haushalt (`ai_usage`, `AI_DAILY_LIMIT_PER_HOUSEHOLD`, Standard 50) mit Token-Zählern aus `response.usage` und pro Person über alle Haushalte (`ai_user_usage`, `AI_DAILY_LIMIT_PER_USER`, Standard 20, 429 `AI_USER_DAILY_LIMIT_REACHED`); Reservierung per Upsert `ON CONFLICT DO UPDATE … WHERE calls < limit` (CASA-32), Rückgabe bei jedem Fehler ohne API-Antwort (CASA-33)
  - Rezeptvorschlag im Format von `RecipeCreate`, nicht gespeichert; Speichern über den Rezept-Endpunkt, fehlende Zutaten über den Shopping-Endpunkt
  - Pflanzenpflege unabhängig von einem Plant-Modell (Intervalle, Lichtbedarf, Giftigkeit für Haustiere mit Hinweis „keine tierärztliche Auskunft“); Schema dokumentiert als Vorlage für das Pflanzen-Modul
  - Prompts DE/EN nach Sprache der Oberfläche; Nutzereingaben als escapter JSON-Block, Rolle nur im Systemprompt
  - Rezepte erhalten `steps` und `tags` (Schema, Endpunkte, Anzeige)
- **Backend:** `services/ai/` (`client`, `prompts`, `schemas`, `recipe`, `plant_care`, `usage`, `errors`, `text`), `routers/ai.py`, `models.py` (`Household.ai_enabled`, `AiUsage`, `Recipe.steps/tags`), `core/config.py`, `core/error_codes.py` (`AI_*`), `routers/auth.py` (`/me` mit `ai_enabled`), `routers/food.py`
- **Migrationen:** `c8d9e0f1a2b3_add_recipe_steps_and_tags`, `y1z2a3b4c5d6_add_ai_assistant` (einziger Kopf `y1z2a3b4c5d6`); auf PostgreSQL 16 hin und zurück geprüft
- **Frontend:** `stores/ai.ts`, `repositories/aiRepository.ts`, `components/AiRecipeCard.vue`, `components/AiSettingsCard.vue`, `views/AssistantView.vue` (`/assistant`), FoodView (Karte + Schritte in den Details), HouseholdView, MoreSheet (Eintrag nur bei aktivem Assistenten), `stores/auth.ts` (`ai_enabled` aus `household_updated`)
- **Betrieb:** `.env.example`, `.env.prod.example`, beide Compose-Dateien; `nginx.conf` mit `proxy_read_timeout 200s` für die KI-Endpunkte
- **Tests:** 55 Backend-Tests in `test_ai_assistant.py` (Client gemockt), 4 in `test_recipe_steps_tags.py`; 15 Vitest-Tests in `stores/__tests__/ai.test.ts`, 1 neuer im Auth-Store-Test
- **Reviews:** Security-Review `docs/security/ai-assistant-review.md` (kein kritischer/hoher Befund; offen A-01: Tageslimit pro Haushalt lässt sich über weitere Haushalte vervielfachen)
- **i18n:** 73 neue Keys (`ai.*`, `errors.AI_*`, `errors.RATE_LIMITED`, `nav.assistant`, `moreSheet.assistantSub`, `food.steps`) → 773 Keys total
- **Nicht gemessen:** kein echter API-Aufruf (kein Schlüssel in der Entwicklungsumgebung); Kosten-Schätzung in `docs/ai-assistant.md`

### Epic 34: Pflanzen × KI × Tags ✅
- **Abgeschlossen:** 2026-10-06 (Branch `claude/plants-ai-tags-integration`)
- **Teil 1 — KI-Pflegehinweise im Pflanzen-Modul:** Button „Pflegehinweise von der KI holen“ im „Pflanze hinzufügen“-Dialog und in der Detailansicht, sichtbar nur bei Server-Schlüssel und Haushalts-Opt-in (`aiStore.enabledForHousehold`). Der Vorschlag (Intervalle, Licht, Standort, Giftigkeit mit „Keine tierärztliche Auskunft“) wird angezeigt und erst auf Tipp übernommen: Pflegeaufgaben `water`/`fertilize`/`repot` anlegen bzw. bei abweichendem Intervall aktualisieren (Umtopfen Monate × 30; `null` → keine Aufgabe), `care_notes` an das Freitextfeld anhängen, botanischer Name füllt eine leere Art. Im Anlegen-Dialog wird erst beim Speichern etwas geschrieben. Kein neuer Endpunkt, keine Migration.
  - **Frontend:** `components/AiPlantCareCard.vue`, `components/AiPlantAdvice.vue` (Anzeige, vom Assistenten mitgenutzt), `utils/plantCare.ts` (`adviceTasks`, `planAdvice`, `mergeCareNotes`), `stores/plants.ts` (`applyAdviceTasks`, `applyCareAdvice`; liest die Aufgaben frisch, bei Fehler Abbruch statt Duplikate), `PlantsView`, `PlantDetailView`, `AssistantView`
- **Teil 2 — Tag-Zieltyp Pflanze:** Registry-Einträge `plant.water` (Zieltyp `plant`; ein Ziel = alle Gießaufgaben der Pflanze, leer = alle fälligen Gießaufgaben über `water_all`) und `plant.care_task.done` (Zieltyp `plant_care_task`, Ziel = Pflegeaufgabe; eigener Zieltyp, weil das Ziel-Dropdown pro Zieltyp nur eine Zielliste kennt). Mutationen über `complete_care_task` und `water_all` (gleiche Logs und Socket-Events), `describe` aus `care_status` (Pflanzenname, letzte Gießung, nächste Fälligkeit). Keine Gießaufgabe → `can_execute=false` mit `NO_WATER_TASK` (bei „alle“ `NO_PLANTS`/`NOTHING_DUE`), `execute` → 409 `TAG_NOTHING_TO_DO`. Nach dem Scan führt „Ansehen“ auf `/plants/{id}`.
  - **Backend:** `services/tag_actions.py`; **Frontend:** `utils/tagScan.ts` (`plantWaterLines`, `moduleRouteFor`), `TagScanView.vue`, Typ `TagActionKey`; `TagsView`/`stores/tags.ts` sind generisch und brauchten nur die i18n-Keys
- **Tests:** `test_tags.py` +14 (66): resolve/execute, nur Gießaufgaben, keine Gießaufgabe, gelöschte Pflanze/Aufgabe, fremder Haushalt (403, 422 beim Anlegen), „alle fälligen“; Vitest +13 (`plantCare` +6, `plants` Store +3, `tagScan` +4)
- **Doku:** `docs/security/tags-review.md` (Abschnitt „Zieltyp Pflanze“), README (Tags), `docs/ai-assistant.md` (Einbindung umgesetzt)
- **i18n:** `ai.plant.*` (+10), `tags.targetTypes/targetNone/actions.plant.*/scan.*` (+19) → 993 Keys total
- **Offen:** Der Vorschlag wird nicht gespeichert (Giftigkeit, Lichtbedarf und Standort-Tipp sind nur in der Vorschau sichtbar, nur `care_notes` landet in der Pflanze); Mehrfach-Scan von `plant.water` loggt mehrfach (siehe Review); nicht gegen die echte Anthropic-API geprüft (Client in Tests gemockt)
