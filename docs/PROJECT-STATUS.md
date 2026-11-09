# Casa (haushalt-app) — Projektstand

**Stand:** 2026-11-09. Dieses Dokument beschreibt, was die App tut, wie sie aufgebaut ist und welche Regeln nirgendwo sonst stehen. Es enthält bewusst keine Dateilisten, keine Endpoint-Liste und keine Änderungshistorie: Die API-Doku erzeugt das Backend selbst (OpenAPI unter `/docs`), die Historie steht in Git und in [`CHANGELOG.md`](../CHANGELOG.md).

Zahlen, die sich ständig ändern, stehen nur im Abschnitt „Kennzahlen“, mit Datum und dem Befehl, der sie erzeugt. Alles andere im Dokument ist nicht datumsabhängig. Wer eine Zahl braucht, führt den Befehl aus, statt sie hier nachzuschlagen.

---

## 1. Überblick

Casa ist eine Haushalt-App für gemeinsame Einkaufslisten, Aufgaben, einen Putzplan mit Ämtli-Rotation, Ausgaben-Teilung mit Ausgleichszahlungen, Budget und wiederkehrende Rechnungen, Kalender mit Abstimmungen, Essensplanung, Haustiere, Pflanzen, Notizen und eine Dokument-Ablage. Mehrere Personen teilen sich einen Haushalt, eine Person kann in mehreren Haushalten sein. Änderungen kommen per WebSocket in Echtzeit bei allen an. Die Oberfläche ist mobil zuerst gedacht, als PWA installierbar, mit Web Push, zweisprachig (DE/EN). Optional gibt es einen KI-Assistenten (Rezeptvorschläge, Pflanzenpflege-Hinweise), der nur mit Server-Schlüssel und Opt-in des Haushalts läuft.

| Bereich | Technologie |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Socket.IO (`python-socketio`), `slowapi` für Rate-Limits |
| Datenbank | PostgreSQL 16 (Produktion), SQLite in-memory für die schnelle Testlane |
| Frontend | Vue 3, TypeScript, Vite, Pinia, vue-i18n, PWA (`vite-plugin-pwa`), Phosphor Icons |
| Auth | JWT-Access-Token (15 Min., nur im Speicher), rotierender Refresh-Token (30 Tage) als HttpOnly-Cookie `casa_rt` mit `SameSite=Strict` und CSRF-Header `X-Requested-With: casa`, bcrypt |
| Mehrere Prozesse | Redis für Rate-Limits (`RATE_LIMIT_STORAGE_URI`) und die Socket.IO-Message-Queue (`SOCKETIO_MESSAGE_QUEUE`); ohne Redis genau ein Prozess |
| KI (optional) | Anthropic-API über das offizielle `anthropic`-SDK, Modell `claude-opus-5-5`, Structured Outputs |
| Betrieb | Docker Compose (Entwicklung und Produktion hinter Nginx Proxy Manager), Backup-/Restore-Skripte, optional Sentry (`SENTRY_DSN`) |
| CI | GitHub Actions, Jobs `backend`, `backend-postgres`, `frontend`, `dependency-audit` (siehe `.github/workflows/ci.yml`) |

Exakte Versionen stehen in `backend/requirements.txt` und `frontend/package-lock.json`.

## 2. Kennzahlen (erhoben am 2026-11-09)

| Grösse | Wert | Befehl |
|---|---|---|
| Backend-Tests | 1268 bestanden, 80 übersprungen, Coverage 94 % | `cd backend && pytest -q --cov=app` |
| PostgreSQL-Lane | zusätzlich, nur mit `TEST_PG_URL` | `pytest -m pg -q` (siehe [`backend/tests/pg/README.md`](../backend/tests/pg/README.md)) |
| Frontend-Coverage | 82,5 % Statements, 77 % Branches | `cd frontend && npm run test:coverage` |
| i18n-Schlüssel | 1462 je Sprache | `cd frontend && npm run check:locales` |
| Router-Module / Registrierungen | 27 Dateien, 34 `include_router`-Aufrufe | `ls backend/app/routers \| grep -vc __` und `grep -c include_router backend/app/main.py` |
| API-Endpoints | 178 plus `GET /api/health` | `grep -rhE "^@[a-z_]*router\.(get\|post\|put\|patch\|delete)\(" backend/app/routers \| wc -l` |
| Tabellen | 45 | `grep -c __tablename__ backend/app/models.py` |
| Alembic-Revisionen | 50, ein Kopf (`b4c5d6e7f8a9`) | `ls backend/migrations/versions/*.py \| wc -l` und `alembic heads` |
| Frontend | 25 Views, 19 Stores, 23 Repositories | `ls frontend/src/views frontend/src/stores frontend/src/repositories` |

Die Frontend-Coverage misst nur `src/utils/`, `src/stores/` und `src/repositories/` (siehe `frontend/vitest.config.ts`); Views und Komponenten sind nicht Teil der Messung. Die Schwellen in der Konfiguration (66 % Statements) liegen bewusst unter dem erreichten Stand und lassen die CI scheitern, wenn die Abdeckung fällt.

## 3. Architektur

```
Vue-Views und Komponenten
   │  rufen Aktionen auf
Pinia-Stores ── optimistische Updates, Rollback, Socket-Handler
   │
Repositories ── dünne Schicht um Axios (Naht für späteren Offline-Betrieb)
   │                                   ▲
Axios (REST) ──── HTTPS ──── FastAPI   │ Socket.IO (WSS)
                               │       │
                   Routers → Services → SQLAlchemy → PostgreSQL
                               └── Socket.IO-Server: Raum pro Haushalt
Hintergrund-Tasks im Backend: Web-Push-Scheduler, Aufräumen verwaister Uploads
```

**Backend (`backend/app/`).** `routers/` enthält die HTTP-Endpoints, je Modul eine Datei. `services/` enthält fachliche Regeln, die mehrere Router teilen (Salden, Mitgliedschaft, Putzplan-Planung, Push, Tag-Aktionen, KI, Tarife). `core/` enthält Konfiguration (`config.py`, alle Einstellungen per Umgebungsvariable), Auth-Dependencies (`deps.py`), Fehlercodes (`error_codes.py`), Rate-Limiter, Security-Header-Middleware und die globalen Datenbankfehler-Handler. Alle Pfade gelten ohne Weiterleitung (`redirect_slashes=False`): Der abschliessende Slash muss exakt stimmen.

**Mehrmandantenfähigkeit.** Jeder Endpoint unter `/api/households/{id}/…` prüft die Mitgliedschaft (`verify_household_access`, fremder Haushalt → 403) oder die Admin-Rolle (`verify_household_admin`). Die `*_scoping`-Tests prüfen das für jedes Modul.

**Frontend (`frontend/src/`).** `views/` (Seiten, Routen in `router/index.ts`), `components/` (inklusive `components/ui/` mit den Basiskomponenten und dem Design-System aus `assets/theme.css`, Tokens in [`design/design-tokens.md`](design/design-tokens.md)), `stores/`, `repositories/`, `composables/`, `utils/`, `locales/`. Die App-Shell (`App.vue`) zeigt ab 768 px eine Top-Bar mit sechs Links (Start, Kalender, Einkauf, Aufgaben, Finanzen, Haushalt), darunter die Bottom-Nav mit vier Tabs (Start, Kalender, Aufgaben, Einkauf) und dem Eintrag „Mehr“. Das „Mehr“-Sheet führt zu Finanzen, Tieren, Pflanzen, Essen, Notizen, Dokumenten und Einstellungen; der Assistent erscheint dort nur, wenn die KI für den Haushalt aktiv ist. Der Inhalt ist auf 640 px Breite begrenzt, Touch-Ziele sind mindestens 44 px gross.

**Muster in den Stores.**
- Optimistische Updates mit Rollback bei Serverfehlern; Toast als Rückmeldung.
- Neue Einträge bekommen die ID vom Client (`pendingTempIds`, idempotentes Anlegen). Ein Retry sendet dieselbe ID.
- Schnelle Mehrfachklicks fängt ein Mutex pro Eintrag ab (`pendingToggles`).
- Socket-Events sind idempotent, der Server gewinnt. Wo Tabellen `version` führen (siehe Datenmodell), verwirft `utils/syncVersion.ts` veraltete Events.
- Eine Haushalts-/Sitzungs-Generation (`utils/householdGuard.ts`, `stores/householdScope.ts`) verwirft Antworten, die nach einem Haushaltswechsel oder Logout eintreffen. Ein Haushaltswechsel leert alle Stores.
- `DELETE` mit 404 gilt als Erfolg (schon gelöscht).
- Eine Version-Konflikt-Antwort (`If-Match`, 409) übernimmt den Server-Stand.

### Echtzeit (Socket.IO)

Der Client verbindet sich unter `/socket.io` mit dem Access-Token und tritt mit `join_household` dem Raum `household_<id>` bei; die Mitgliedschaft wird vor und nach dem Beitritt geprüft. Jede Person hat zusätzlich einen persönlichen Raum `user_<id>`. Server-Events folgen dem Namensschema `<entität>_created|updated|deleted`; die Payloads sind die Response-Schemas der REST-Endpoints (Löschungen nur `{ id, … }`). Die vollständige Liste steht im Code (`grep -rn "emit_to_household" backend/app`).

Eine Verbindung lebt nur so lange wie das Access-Token, mit dem sie zuletzt authentifiziert wurde:
- **connect:** Der Server prüft das JWT, merkt sich `user_id` und `exp` und startet einen Timer auf `exp`.
- **Verlängern:** Nach jedem Token-Refresh schickt der Client `reauth` mit dem neuen Token. Gehört es zum selben User, setzt der Server den Timer neu; Räume bleiben erhalten. `reauth` prüft zudem die Haushaltsräume erneut und wirft die Verbindung aus Räumen ohne Mitgliedschaft.
- **Ablauf:** Der Server sendet `session_ended` (`expired`) und trennt. Der Client holt per Refresh ein neues Token und verbindet neu.
- **Logout und Reuse-Erkennung:** `/api/auth/logout` trennt alle Verbindungen der Person (`session_ended` mit `logout`), die Reuse-Erkennung mit `revoked`. Das Access-Token trägt keine Geräte-Kennung, deshalb trifft das auch andere Geräte. Diese verbinden sich mit ihrem noch gültigen Token sofort neu, aber ohne Refresh: Der Refresh-Token könnte gerade widerrufen sein (zweiter Tab), und ein Refresh würde die Reuse-Erkennung auslösen und alle Geräte abmelden.
- **Fehler beim Beitritt** kommen als Event `error`; bei fehlender Mitgliedschaft mit `code: "NOT_HOUSEHOLD_MEMBER"` (der Client lädt dann `/me` neu).
- Wird eine Person entfernt oder verlässt sie den Haushalt, wirft der Server ihre Verbindungen nach dem Event aus dem Raum.
- Der Client lädt Stores nur bei Anmeldung, Haushaltswechsel und Reconnect nach, nicht nach jedem Token-Refresh. Der Sync-Punkt zeigt „Verbunden“ erst, wenn `join_household` bestätigt ist. `useSocket.on` verwirft Payloads mit der `household_id` eines anderen Haushalts.

Warum Ablauf-Timer und `reauth` statt einer Prüfung bei jedem Event: Fast der ganze Verkehr läuft vom Server zum Client. Ein Client, der nur zuhört, schickt nach `join_household` nichts mehr und würde bei einer reinen Event-Prüfung nie getrennt. Ohne `reauth` müsste jede Verbindung alle 15 Minuten neu aufgebaut werden.

Mit `SOCKETIO_MESSAGE_QUEUE` (Redis) laufen mehrere Backend-Prozesse; Trennen und Rauswerfen gehen dann über einen Redis-Kontrollkanal an alle Prozesse (`socket_manager.py`). Details zu Redis und Mehrprozess-Betrieb: [`deployment.md`](deployment.md), Abschnitt 8.

## 4. Module

Jedes Modul besteht aus Router, Store, Repository und View (falls vorhanden). Die Tabelle nennt jeweils den Einstieg.

| Modul | Backend | Frontend |
|---|---|---|
| Registrierung, Login, Sitzung | `routers/auth.py` | `LoginView`, `RegisterView`, `stores/auth.ts` |
| Konto: Passwort vergessen/ändern, E-Mail-Bestätigung, Konto löschen | `routers/account.py` | `ForgotPasswordView`, `ResetPasswordView`, `VerifyEmailView`, `AccountSettingsCard` |
| Haushalt, Mitglieder, Einladungscode | `routers/households.py`, `services/membership.py` | `HouseholdView`, `NoHouseholdView` |
| Dashboard, Zahl am App-Icon | `routers/dashboard.py`, `services/attention.py` | `DashboardView` |
| Einkauf | `routers/shopping.py` | `ShoppingView`, `ShoppingList` |
| Aufgaben (Todos, Erinnerungen) | `routers/todos.py` | `TodosView`, `TodoList` |
| Putzplan / Ämtli | `routers/chores.py`, `services/chore_scheduler.py` | `ChoresView` (Route `/chores`, nicht in der Top-Bar; Zugang über „Ämtli verwalten“ in den Aufgaben) |
| Ausgaben, Salden, Ausgleich | `routers/expenses.py`, `routers/settlements.py`, `services/balance_service.py` | `ExpensesView`, `BalanceSummary`, `FinanceHistory` |
| Budget, wiederkehrende Rechnungen | `routers/budgets.py`, `routers/recurring_bills.py` | `ExpensesView`, `RecurringBillsManager` |
| Kalender, Termine | `routers/calendars.py`, `routers/events.py`, `services/event_times.py` | `CalendarView`, `CalendarMonthGrid` |
| Abstimmungen (Termin und Essen) | `routers/polls.py` | in `CalendarView` und `FoodView` |
| Haustiere | `routers/pets.py`, `services/care_schedule.py` | `PetsView`, `PetDetailView` |
| Pflanzen | `routers/plants.py` | `PlantsView`, `PlantDetailView` |
| Essen: Rezepte, Wochenmenü | `routers/food.py` | `FoodView`, `RecipeManager` |
| Notizen | `routers/notes.py` | `NotesView` |
| Dateien, Dokument-Ablage | `routers/files.py`, `routers/documents.py`, `services/storage.py`, `services/file_cleanup.py` | `DocumentsView` |
| Web Push | `routers/push.py`, `services/push_service.py` | `PushSettings`, `pwa.ts`, `public/push-sw.js` |
| Tags (NFC/QR) | `routers/tags.py`, `services/tag_actions.py` | `TagsView`, `TagScanView` (`/t/:token`) |
| KI-Assistent | `routers/ai.py`, `services/ai/` | `AssistantView`, `AiRecipeCard`, `AiPlantCareCard`, `AiSettingsCard` |
| Homescreen-Widget (Scriptable) | `routers/widget.py` | `WidgetSettingsCard`; siehe [`widget.md`](widget.md) |
| Tarife, Abrechnung (Stripe) | `routers/billing.py`, `services/entitlements.py`, `services/billing/` | `BillingCard` |
| Betreiber-Ansicht (Plattform-Admin) | `routers/admin.py` | `AdminView` (`/admin`) |
| Öffentliche Konfiguration, Rechtstexte | `routers/meta.py` | `LegalView`, `LegalLinks`; Vorlagen in `frontend/public/legal/` |

## 5. Datenmodell

Alle Tabellen stehen in `backend/app/models.py`. Geldbeträge sind Integer in Rappen (`*_rappen`), im Frontend parst `utils/money.ts` Eingaben ohne Fliesskomma. Haushaltsdaten tragen `household_id` (FK auf `households`, `ON DELETE CASCADE`). Verweise auf `users` in Ersteller-, Zuweiser- und Erledigt-von-Spalten sind `SET NULL`; die Buchhaltungs-Spalten sind `RESTRICT` (siehe Invarianten).

```
User ──< HouseholdMember >── Household (invite_code, timezone, currency, plan, ai_enabled)
 ├──< RefreshToken, PushSubscription, UserToken, WidgetToken
 │
Household ├── ShoppingList ──< ShoppingItem
          ├── Todo ──< TodoReminder, TodoAssignee
          ├── Expense ──< ExpenseShare;  Settlement;  Budget;  RecurringBill
          ├── Chore ──< ChoreAssignment
          ├── Calendar ──< Event;  EventPoll ──< EventPollOption ──< EventPollVote
          ├── Pet ──< FeedingLog, Medication ──< MedicationLog, PetCareTask
          ├── Plant ──< PlantCareTask, PlantCareLog
          ├── Recipe;  MealPlanEntry (>── Recipe)
          ├── Note;  Tag
          ├── StoredFile >──< Document (über DocumentFile)
          ├── Subscription, BillingEvent
          └── AiUsage; AiUserUsage; AiBudgetCounter; AiCallReservation (Kontingente)
```

**Synchronisations-Felder.** `SyncVersionMixin` (`updated_at` und `version`, startet bei 1, wird bei jeder ORM-Änderung atomar erhöht) steckt in `shopping_lists`, `shopping_items`, `todos` und `chore_assignments`. `expenses` führt eine eigene `version` (für `If-Match`). Nur `updated_at` haben `budgets`, `notes`, `documents` und `subscriptions`. Core-`UPDATE`-Statements müssen `version` selbst erhöhen. Die Clients verwerfen anhand der Version veraltete Socket-Events.

**Invarianten**
- `SUM(expense_shares.amount_rappen) == expenses.amount_rappen`; erzwungen im Service-Layer, nicht per DB-Constraint.
- PATCH: ein weggelassenes Feld bleibt unverändert, `null` leert es. Für NOT-NULL-Spalten antwortet die API mit 422 (Basisklasse `PatchModel`, aus dem ORM-Modell abgeleitet). Ausnahme: `ingredients`/`steps`/`tags` von Rezepten, dort wird `null` zu `[]`. NOT-NULL-JSON-Spalten speichern Python-`None` nie als JSON-`null` (`JSON(none_as_null=True)`).
- Parallele Schreibkonflikte, die nicht fachlich behandelt werden (Deadlock, Serialisierung, Lock-Timeout, Integritätsfehler), liefern 409 `CONFLICT_RETRY` statt 500 (`core/db_errors.py`). Fachliche Check-then-Act-Abläufe sperren vorher Zeilen (`services/locking.py`: `lock_household`, `lock_row`; auf SQLite ein No-Op).
- `households.timezone` (Default `Europe/Zurich`) steuert Putzplan-Daten, Termin-Uhrzeiten, Fütterungs- und Pflegetage sowie die Kalenderdaten der Finanzen (Buchungsmonat, Standard-Monat von Budget und Übersicht, Standard-Datum von Ausgaben/Ausgleich; `services/household_time.py`).
- Ledger-FKs auf `users` sind `RESTRICT` (`expense_shares.user_id`, `settlements.from_user_id`/`to_user_id`, `expenses.paid_by_user_id`): Ein `DELETE FROM users` mit Buchungen schlägt fehl, statt Salden still zu verschieben. Festgehalten in `tests/pg/test_pg_smoke.py::test_ledger_user_fks_restrict`.
- Schema = Modelle: Jeder DB-Server-Default hat ein Modell-Pendant (`server_default`). Der Drift-Check `tests/pg/test_pg_smoke.py::test_models_match_migrations` vergleicht Tabellen, Spalten, Typen, Nullability, FKs und Server-Defaults. Alle Migrationen lassen sich bis `base` zurückrollen; im Betrieb gilt trotzdem forward-only (siehe [`deployment.md`](deployment.md), Abschnitt 4).
- Beim Löschen eines Haushalts leert `CASCADE` alle Tabellen. Die Dateien auf dem Datenträger entfernt der Router beim Auflösen; bleibt etwas liegen, räumt `services/file_cleanup.py` periodisch auf (verwaiste Uploads ohne Zuordnung und Dateien im Storage ohne DB-Zeile, älter als 24 h).

## 6. Geschäftsregeln

### Rollen, Haushalt, Mitgliedschaft
- Zwei Rollen: `admin` und `member`, keine feineren Berechtigungen (bewusst). Admin-only: Haushalt umbenennen, Mitglied entfernen, Einladungscode erneuern, KI-Opt-in, Tags anlegen/ändern/löschen/Token neu erzeugen. Scannen und Ausführen eines Tags dürfen alle Mitglieder. Der Plattform-Admin (`users.is_platform_admin`) ist davon getrennt und wird nur per `python -m scripts.make_platform_admin --email …` vergeben.
- Registrierung: genau eines von `household_name` oder `invite_code`. Mit Haushaltsname entsteht ein neuer Haushalt mit Admin über denselben Helfer wie `POST /api/households/` (`create_household_with_admin`: Einladungscode mit Ablauf, Default-Kalender „Allgemein“); mit Code wird die Person `member`. Parallele Registrierung derselben E-Mail → 400 `EMAIL_ALREADY_REGISTERED`.
- Einladungscodes laufen nach 7 Tagen ab (`INVITE_CODE_TTL`, `households.invite_code_expires_at`; `NULL` = läuft nicht ab). Ein neuer Code entsteht beim Anlegen, bei jeder Rotation (Admin-Button, Entfernen eines Mitglieds). Unbekannter oder rotierter Code → 404 `INVITE_CODE_NOT_FOUND`, abgelaufen → 410 `INVITE_CODE_EXPIRED`, schon Mitglied → 409 `ALREADY_MEMBER`. Der Code ist für alle Mitglieder sichtbar.
- Beitreten, Verlassen und Entfernen sperren zuerst die `households`-Zeile und prüfen danach (`services/membership.py`). Nach jedem Commit gilt: mindestens ein Admin, solange es Mitglieder gibt; keine Mitglieder → Haushalt gelöscht. Fehlt der Admin, wird das dienstälteste Mitglied (frühestes `joined_at`, dann `user_id`) befördert. Es gibt keinen manuellen Admin-Transfer.
- Eine Währung pro Haushalt (`households.currency`, Default `CHF`). Ausgaben und Ausgleiche müssen sie verwenden, sonst 422 `CURRENCY_MISMATCH`. Kein Multi-Currency (bewusste Entscheidung).

### Haushalt verlassen und Mitglied entfernen
- Verlassen ist immer erlaubt, auch mit offenem Saldo. Ausgaben und Anteile bleiben bestehen („Ehemaliges Mitglied“-Muster). Das letzte Mitglied löst den Haushalt samt Dateien auf.
- Offene Zuständigkeiten werden im selben Commit freigegeben: Die Person verschwindet aus den Zuständigen offener Aufgaben (war sie allein, ist die Aufgabe offen für alle), offene Einkaufsartikel und offene Ämtli-Termine werden niemandem zugewiesen, sie wird aus `rotation_order` aller Ämtli entfernt (`next_rotation_index` so angepasst, dass die Reihenfolge der Übrigen erhalten bleibt), der Standard-Zahler wiederkehrender Rechnungen wird leer (Buchen verlangt dann einen Zahler, `BILL_PAYER_REQUIRED`), Stimmen in offenen Umfragen werden gelöscht, der Widget-Schlüssel für diesen Haushalt wird gelöscht. Erledigte Aufgaben/Ämtli, Ausgaben, Ausgleiche und entschiedene Umfragen behalten die Person.
- Das Event `household_member_left` bzw. `household_member_removed` trägt `released` (betroffene Bereiche); andere Clients laden diese Listen neu.
- Der Einladungscode bleibt beim freiwilligen Austritt unverändert: Wer geht, kann innerhalb der Gültigkeit wieder beitreten, ohne alte Zuständigkeiten und ohne alten Widget-Schlüssel.
- Entfernen: Admins dürfen nur `member` entfernen (andere Admins → 403 `CANNOT_REMOVE_ADMIN`, sich selbst → 422 `CANNOT_REMOVE_SELF`); Rolle und Mitgliedschaft des Aufrufers werden unter der Haushaltssperre neu geprüft. Danach wird der Einladungscode erneuert.
- Zuweisungen an Nicht-Mitglieder (Altbestand) gelten in Badge, Widget und Dashboard als „niemandem zugewiesen“.

### Sitzungen und Konto
- `/refresh` sperrt den alten Token (`FOR UPDATE`); Widerruf, `replaced_by_id` und Nachfolger entstehen in einem Commit. Ein bereits ersetzter Token wird innerhalb von 30 Sekunden (`REFRESH_TOKEN_REUSE_GRACE_SECONDS`) toleriert (zweiter Tab, PWA): Der Server folgt der Ersetzungskette zum aktiven Nachfolger und rotiert diesen. Ausserhalb des Fensters oder ohne Nachfolger gilt es als Wiederverwendung: alle Tokens der Person werden widerrufen, die Sockets getrennt. Ein Logout ist nie für diese Kulanz zugelassen.
- Passwort ändern und Passwort-Reset widerrufen alle Refresh-Tokens (der Aufrufer von „Passwort ändern“ bekommt ein neues Paar). Ein eigener „Überall abmelden“-Endpoint existiert nicht.
- **Konto-Löschung** (`DELETE /api/account`, Passwort nötig): Die Person verlässt alle Haushalte nach den Austrittsregeln, die `users`-Zeile bleibt anonymisiert bestehen (`email` → `deleted-<id>@deleted.invalid`, `display_name` → „Gelöschtes Konto“, unbrauchbarer Passwort-Hash, `deleted_at` gesetzt, Sitzungen widerrufen, Push-Abos gelöscht). Buchungen behalten die anonyme `user_id`, Salden bleiben unverändert. Die Zeile wird nicht hart gelöscht, weil Buchhaltung, Termine, Abstimmungen und Logs auf sie verweisen.
- E-Mail-Versand (Reset, Bestätigung, Hinweise) läuft über SMTP; ohne `SMTP_HOST` werden Mails in der Entwicklung nur geloggt und in Produktion bleiben die Funktionen ausgeblendet (`MAIL_BACKEND=auto`).
- Tarife: Mit `BILLING_ENABLED=false` (Standard) hat jeder Haushalt alle Funktionen mit den globalen Limits. Mit `true` gibt es `free` und `premium` mit eigenen Limits für Mitglieder, Speicher und KI (`services/entitlements.py`); Premium kommt über Stripe oder manuell durch den Plattform-Admin. Details: [`monetization.md`](monetization.md).

### Aufgaben
- Eine Aufgabe hat beliebig viele Zuständige (`todo_assignees`, API maximal 10); keine Zuständigen heisst offen für alle.
- Eine Person hakt für alle ab: `done_by_user_id` hält fest, wer (Anzeige „erledigt von …“); Wiedereröffnen leert es.
- „Ich übernehme“ (`POST …/claim`) trägt den Aufrufer zusätzlich ein, auch wenn andere schon zuständig sind. Es ist idempotent (PK `(todo_id, user_id)` mit `ON CONFLICT DO NOTHING`, ohne Änderung kein Event); eine erledigte Aufgabe → 422 `TODO_IS_DONE`.
- „Meine“ Aufgaben (`assigned_to_me`, Personen-Filter, Badge, Widget): die Person ist eine der Zuständigen. Aufgaben ohne Zuständige oder nur mit Ex-Mitgliedern zählen in Badge und Widget für alle. Jede Änderung der Zuständigen erhöht `version`.
- Erinnerungen: höchstens 5 pro Aufgabe, nicht an erledigte Aufgaben (`TODO_IS_DONE`), keine Vergangenheit (`REMINDER_IN_PAST`). `remind_at` ohne Offset gilt als Wanduhrzeit des Haushalts. Push geht an alle zuständigen aktuellen Mitglieder, sonst an alle.

### Putzplan
- Die Rotation ist kalenderbasiert, nicht erledigungsbasiert. Zuweisungen entstehen lazy (beim Abfragen von `…/chores/assignments`, im Push-Scheduler und beim Tag-Scan), ohne Cron. Das Abfragefenster beträgt höchstens 92 Tage. Wiederholungen: `weekly`, `biweekly`, `monthly`.
- Nur eine echte Änderung von Wiederholung, Wochentag oder Monatstag setzt den Zeitplan neu (Umbenennen tut es nicht, die Rotation springt nicht). Dann werden offene Zuweisungen ab morgen gelöscht und ab `anchor_date` neu geplant (nie überfällig). Pausieren löscht offene Zuweisungen ab heute (Rotationsplätze kommen zurück); Reaktivieren setzt einen neuen `anchor_date` ab heute, ohne Nachholen. Das Event `chore_assignments_deleted` trägt die gelöschten IDs.
- Abhaken und Rückgängig sind idempotent.

### Einkauf
- Geschäfte (`store`) sind abgeleitete Freitext-Werte, keine Tabelle. Sie werden beim Anlegen, Ändern und Umbenennen normalisiert (trim, Mehrfach-Whitespace, leer → `null`) und ohne Beachtung der Schreibweise zusammengeführt; kanonisch ist die häufigste Schreibweise, bei Gleichstand alphabetisch. Der Vergleich läuft in Python (`str.lower`), damit SQLite und PostgreSQL gleich arbeiten; das Frontend spiegelt das in `utils/storeName.ts`.
- `bulk-add` (fehlende Zutaten aus Rezept, Menüplan und KI) überspringt Einträge, die auf irgendeiner Liste noch offen sind (ohne Beachtung von Schreibweise und führender Menge) und ist idempotent.

### Finanzen
- Ausgaben haben `version`; `PATCH` mit `If-Match: <version>` antwortet bei veraltetem Stand mit 409 `EXPENSE_VERSION_CONFLICT`. Löschen ist ein Soft Delete (`deleted_at`, `deleted_by`), die Anteile bleiben; gelöschte Ausgaben und Ausgleiche lassen sich wiederherstellen und zählen bis dahin nicht in Salden. Ein Wiederherstellen einer Rechnungsbuchung, deren Monat inzwischen neu gebucht wurde, → 409 `BILL_ALREADY_BOOKED`.
- Grenzen (`services/finance_rules.py`): Betrag höchstens 10^9 Rappen, Datum innerhalb von ±10 Jahren, doppelte Teilnehmer werden abgelehnt.
- Salden: Greedy-Ausgleichsvorschläge; ehemalige Mitglieder behalten ihren Saldo (`is_member`, `display_name`).
- Ausgleichszahlungen: Anlegen mit Client-ID ist idempotent. `POST …/settlements/check` und die Antwort-`warnings` melden `DUPLICATE_RECENT` und `EXCEEDS_OPEN_DEBT`, ohne zu blockieren.
- Wiederkehrende Rechnungen: eine nicht gelöschte Buchung pro Rechnung und Monat (Unique `(recurring_bill_id, booked_month)`); Nachbuchen bis 12 Monate zurück, nie im Voraus; nur `split_type` `even`.

### Kalender und Abstimmungen
- Termine gehören zu einem Kalender (Name, Farbe, Position). Ein Kalender lässt sich nur löschen, wenn er leer und nicht der letzte ist (`CALENDAR_NOT_EMPTY`, `LAST_CALENDAR`).
- Termin-Zeiten werden als UTC gespeichert und als Wanduhrzeit der Haushalts-Zeitzone angegeben. Eine Zeit in der Sommerzeit-Lücke → 422 `EVENT_TIME_NONEXISTENT`, die doppelte Stunde gilt als erstes Auftreten. Teilnehmer sind aktuelle Mitglieder. Erinnerungen: `none`/`15m`/`1h`/`1d`; ganztägige Termine erinnern um 08:00 am Tag bzw. am Vortag.
- Abstimmungen: eine Stimme pro Person und Abstimmung (DB-Constraint). `decide` legt aus einer Terminumfrage einen Termin an und sendet den vollständigen `EventResponse`; `meal-decide` setzt einen Wochenmenü-Eintrag, ein belegter Tag → 409 `MEAL_PLAN_OCCUPIED`, `replace: true` ersetzt.

### Haustiere und Pflanzen
- Haustiere: Archivieren (`archived`) lässt den Verlauf bestehen und nimmt das Tier aus Fütterung, Dashboard, Badge, Push und Tag-Zielen; Fütterung eines archivierten Tiers → 422 `PET_ARCHIVED`. Endgültiges Löschen mit Verlauf nur mit `?force=true`, sonst 409 `PET_HAS_HISTORY` mit Zahlen; die App bietet zuerst „Archivieren“ an.
- Fütterung: eine pro Tier, Tag und Slot (409 `FEEDING_DUPLICATE`). „Alle füttern“ nutzt einen Savepoint pro Tier und meldet nur tatsächlich angelegte Fütterungen. Das Entfernen einer Fütterung einer anderen Person fragt vorher nach.
- Medikamente: Löschen mit Gaben → 409 `MEDICATION_HAS_HISTORY` (stattdessen deaktivieren); Gabe auf ein deaktiviertes → 422 `MEDICATION_INACTIVE`. Eine Gabe ist immer möglich, auch mehrfach täglich; liegt die letzte weniger als 4 Stunden zurück (`MEDICATION_CONFIRM_HOURS`), fragt die App nach. Mit Client-ID ist ein Retry idempotent.
- Pflegeaufgaben (Tiere und Pflanzen, `services/care_schedule.py`): Eine Intervall-Änderung setzt `next_due_at` auf `letzte Erledigung (oder heute) + Intervall` und `notified_at` zurück. Pflanzen: Pflegeart `water`, `fertilize`, `repot`, `mist`, `other`; Standard-Intervalle 7, 30, 365, 3, 30 Tage. Pro Aufgabe höchstens ein Log pro Haushaltstag: Erledigen und `water-all` setzen die Fälligkeit per `UPDATE … WHERE last_done_at IS DISTINCT FROM heute`; ist die Aufgabe heute schon erledigt, antwortet `…/complete` mit `changed: false`, ohne Event. Log-Einträge überleben das Löschen der Aufgabe.

### Dateien und Dokumente
- Upload: JPEG, PNG, WebP, HEIC/HEIF und PDF, höchstens 10 MB, Magic-Byte-Prüfung. Bilder werden vor dem Decode auf 25 Megapixel geprüft, EXIF-Rotation angewendet und auf 1600 px verkleinert. Das Speicher-Limit pro Haushalt (`HOUSEHOLD_STORAGE_QUOTA_MB`, bei aktiven Tarifen pro Tarif) wird unter Haushaltssperre geprüft. Dateien liegen unter `UPLOAD_DIR/{household_id}/`, der Download ist JWT-geschützt.
- Eine Datei gehört höchstens einem Tier, einer Pflanze oder einem Dokument; Löschen einer referenzierten Datei → 422 `FILE_IN_USE` (Zuordnen und Löschen sperren die Datei-Zeile). Ein Dokument hat bis zu 30 Seiten (`document_files`, umsortierbar).
- Ablaufdaten von Dokumenten lösen eine Push-Erinnerung 30 Tage vorher und am Tag selbst aus.

### Tags (NFC/QR)
- Auf dem Chip oder QR-Code steht nur `https://<host>/t/<token>`; Ziel und Aktion liegen in der Datenbank. Aktionen stehen in der Registry `services/tag_actions.py` (Füttern, Pflegeaufgabe, Ämtli abhaken, Todo abhaken, Einkaufsliste öffnen, Pflanze giessen, Pflanzen-Pflegeaufgabe erledigen); es gibt keine Löschaktionen. Mutationen rufen die bestehenden Funktionen der Module auf (gleiche Validierung, gleiche Socket-Events). Ein neuer Zieltyp braucht einen Registry-Eintrag und i18n-Keys (Anleitung im Modulkopf).
- Der Scan ohne Login führt zum Login und danach zurück auf `/t/<token>`; die Aktion läuft erst nach Tipp auf der Bestätigungsseite (Navigationsaktionen öffnen direkt). `resolve` verändert nichts. `chore.assignment.done` und `plant.water` verlangen das `confirm` aus `resolve` (fehlt → 422 `TAG_CONFIRMATION_REQUIRED`, veraltet → 409 `TAG_CONFIRMATION_STALE`). Schon Erledigtes ist idempotent (`changed=false`, `reason=ALREADY_DONE`).
- Fehler: unbekannter Token → 404, fremder Haushalt → 403, deaktiviert → 410 `TAG_DISABLED`, Ziel gelöscht → 404 `TAG_TARGET_NOT_FOUND`, nichts zu tun → 409 `TAG_NOTHING_TO_DO`. Höchstens 200 Tags pro Haushalt. Tokens werden in den Logs geschwärzt (`core/log_redaction.py`, nginx-Access-Log).
- Fütterungs-Slot nach Tageszeit: ab 14 Uhr Haushaltszeit „Abend“. `chore.assignment.done` nimmt die Zuweisung der laufenden Periode, sonst die nächste innerhalb von 6 Tagen (`CHORE_EARLY_DAYS`).

### Web Push und Zahl am App-Icon
- Der Scheduler im Backend (`services/push_service.py`) versendet Todo- und Termin-Erinnerungen, Pflege von Tieren und Pflanzen (ab 08:00 Haushaltszeit, einmalig pro Fälligkeit über `notified_at`), „Du bist dran“ für den Putzplan und Ablaufdaten von Dokumenten. Jede Payload trägt die Zahl fürs App-Icon (`services/attention.py`, gleiche Regeln wie das Widget: bis heute fällige offene Aufgaben und Ämtli, bei denen die Person zuständig ist oder niemand, sowie Tier- und Pflanzenpflege). Endpoints werden gegen eine Allowlist geprüft (SSRF-Schutz); ein 410 vom Push-Dienst räumt das Abo auf. Ohne VAPID-Schlüssel ist Push aus.
- Das Frontend zeigt die Zahl nur für den Haushalt, den die App gerade zeigt.

### KI-Assistent
- Nur mit `ANTHROPIC_API_KEY` und nur, wenn ein Admin ihn für den Haushalt eingeschaltet hat (`households.ai_enabled`). Ohne Schlüssel meldet `GET /api/ai/status` `enabled: false` und das Frontend blendet alles aus.
- Kostenschutz: 10 Aufrufe pro Minute und IP, Tageskontingente pro Haushalt, pro Person über alle Haushalte und global (UTC-Tag; `AI_DAILY_LIMIT_PER_HOUSEHOLD`/`_PER_USER`/`_GLOBAL`). Eine Reservierung wird vor dem Aufruf committet; nur ein nachweislich vor dem Versand gescheiterter Aufruf wird zurückerstattet, bei unbekanntem Ausgang bleibt er verbucht (`services/ai/usage.py`).
- Rezeptvorschläge und Pflegehinweise werden nicht gespeichert; erst die Übernahme durch die Person schreibt Daten (bei Pflegehinweisen mit Vorschau „alt → neu“ pro Aufgabe). Eingaben gehen als escapter JSON-Block in den Prompt, die Rolle steht nur im Systemprompt. Details: [`ai-assistant.md`](ai-assistant.md).

## 7. Feature-Status

Alle in Abschnitt 4 genannten Module sind implementiert und in der App erreichbar, ebenso Dokument-Ablage mit Mehrseiten-Upload, PWA mit Update-Hinweis, Web Push, Badge, Homescreen-Widget, Tags, KI-Assistent, Konto-Funktionen, Tarife/Stripe und Betreiber-Ansicht. Der Betrieb (Docker, Backups, Restore-Drill) ist in [`deployment.md`](deployment.md) beschrieben.

Seit 2026-11-09 gibt es eine End-to-End-Suite mit Playwright (`frontend/e2e/`, `npm run test:e2e`, CI-Job `e2e`; drei Abläufe: Registrierung/Login, Einkauf zu zweit in Echtzeit, Ausgabe mit Ausgleich) und eine Abnahme-Checkliste ([`qa/ABNAHME-CHECKLISTE.md`](qa/ABNAHME-CHECKLISTE.md)) mit den hier ausgeführten Nachweisen und den Prüfungen, die der Betreiber selbst machen muss. `PetDetailView.vue` und `CalendarView.vue` sind in Unterkomponenten aufgeteilt (`components/pets/`, `components/calendar/`).

### Offen

| Thema | Stand |
|---|---|
| Offline-Betrieb ab M1 | Es gibt kein IndexedDB und keine Änderungs-Warteschlange. Bisher umgesetzt ist M0 (Client-IDs, `version`/`updated_at`, idempotentes Anlegen). Plan, Etappen und die offene Entscheidung E8 (Umgang mit abgehakten Einkäufen): [`offline-first-phase2.md`](offline-first-phase2.md) |
| Dokumente verknüpfen | Dokumente lassen sich nicht mit Ausgaben oder Terminen verknüpfen; es gibt weder Link-Tabelle noch Felder dafür |
| Einladungscode nur für Admins | Offene Produktfrage: Der Code ist für alle Mitglieder sichtbar (Ablauf und Rotation sind umgesetzt) |
| „Überall abmelden“ | Kein eigener Endpoint. Alle Sitzungen enden heute nur durch Passwort ändern/zurücksetzen, Konto löschen oder die Reuse-Erkennung |
| Daten-Export (DSGVO Art. 20) | Kein Export-Endpoint vorhanden (siehe [`monetization.md`](monetization.md), Abschnitt 6) |
| Native Apps | Das Frontend ist für Capacitor vorbereitet (Token-Ablage, `capacitor.config.json`), aber es gibt keine nativen Projekte (`ios/`, `android/`); Web Push läuft nicht in der nativen WebView. Plan: [`mobile-apps.md`](mobile-apps.md) |
| Frontend-Tests | Views und Komponenten sind nicht unter Test und nicht in der Coverage; ohne Test sind die Stores `config`, `dashboard` und `documents`. Schwellen in `vitest.config.ts` nachziehen, wenn die Abdeckung steigt |
| FR/IT | Es gibt nur `de.json` und `en.json` |
| Ämtli-Statistik | „Wer hat wie oft geputzt“ existiert nicht |
| KI-Assistent Etappe 2 | Beleg-Scan per Foto und Wochenplan-Vorschlag sind nur geplant ([`ai-assistant.md`](ai-assistant.md), Abschnitt 9) |

## 8. Bekannte Einschränkungen

| Thema | Details |
|---|---|
| Wiederholtes Anlegen nach Löschen | Löscht jemand einen Eintrag, bevor ein verzögerter Retry mit derselben Client-ID eintrifft, legt der Server ihn neu an (kein Lösch-Vermerk, kein Tombstone). Bewusst zurückgestellt bis Phase 2 |
| Versionierung nur teilweise | `version` gibt es nur auf Einkaufslisten, Einkaufseinträgen, Todos, Putzplan-Zuweisungen und Ausgaben; bei den übrigen Entitäten kann eine REST-Antwort einen neueren Socket-Stand überschreiben |
| `navigator.onLine` | `useConnectivity` stützt sich darauf; Captive Portals und WLAN ohne Internet werden nicht erkannt |
| Start ohne Netz | Das Access-Token wird nie gespeichert. Ohne Netz zeigt die App die Shell („offline eingeloggt“), hat aber kein Token, bis der erste Request nach der Rückkehr des Netzes es per Cookie-Refresh holt. Ohne Offline-Daten (M1) ist das gleichwertig zum früheren Verhalten |
| Logout trennt Sockets aller Geräte | Das Access-Token trägt keine Geräte-Kennung; andere Geräte verbinden sich sofort selbst neu. Ein gestohlenes Access-Token kann bis zu seinem Ablauf (15 Min.) weiter verbinden |
| Rate-Limits | Pro IP. Ohne Redis (`RATE_LIMIT_STORAGE_URI=memory://`) zählt jeder Prozess für sich und die Zähler gehen beim Neustart verloren; dann muss `UVICORN_WORKERS=1` bleiben. Fällt Redis aus, siehe [`deployment.md`](deployment.md), Abschnitt 8 |
| KI-Tageslimit nach UTC-Tag | Die Kontingente zählen pro UTC-Tag, nicht nach der Zeitzone des Haushalts |
| Lange KI-Anfragen hinter Nginx Proxy Manager | Rezeptvorschläge können über 60 s dauern; `frontend/nginx.conf` erlaubt 200 s (`proxy_read_timeout`), Nginx Proxy Manager muss dafür ebenfalls angepasst werden |
| KI nur gegen Mocks entwickelt | Laut [`ai-assistant.md`](ai-assistant.md) entstand der Assistent ohne echten API-Schlüssel; die Tests mocken den Client. Nicht erneut geprüft |
| Keine Geräte-Abnahme | Die Prüfungen laufen automatisiert und lokal; ein Test auf echten iPhones und echter Web-Push-Zustellung liegt nicht vor. Siehe [`qa/current-audit-fixes.md`](qa/current-audit-fixes.md) |
| UI-Audit | Offene Gestaltungspunkte stehen in [`design/ui-audit.md`](design/ui-audit.md) (Stand 2026-10-06, nicht vollständig erneut geprüft) |

## 9. Weiterführende Dokumentation

| Thema | Dokument |
|---|---|
| Einstieg, Start, Prüfungen, Konfiguration | [`../README.md`](../README.md) |
| Produktion, Updates, Rollback, Backups, Redis | [`deployment.md`](deployment.md), [`DEPLOYMENT-WINDOWS-SERVER.md`](DEPLOYMENT-WINDOWS-SERVER.md) |
| Änderungen je Version | [`../CHANGELOG.md`](../CHANGELOG.md) |
| KI-Assistent: Aufbau, Kosten, Schemas | [`ai-assistant.md`](ai-assistant.md) |
| Homescreen-Widget | [`widget.md`](widget.md) |
| Tarife und Abrechnung | [`monetization.md`](monetization.md) |
| Native Apps (Capacitor) | [`mobile-apps.md`](mobile-apps.md) |
| Offline-first: Konzept und Architektur | [`offline-first-phase2.md`](offline-first-phase2.md), [`offline-ready-architecture.md`](offline-ready-architecture.md) |
| Design-Tokens, UI-Audit | [`design/design-tokens.md`](design/design-tokens.md), [`design/ui-audit.md`](design/ui-audit.md) |
| Sicherheits-Reviews | [`security/`](security/), zuletzt [`security/audit-remediation-2026-10-21.md`](security/audit-remediation-2026-10-21.md) |
| Logik-Audit, Geschäftsregel-Matrix, Produktentscheidungen | [`qa/FULL_LOGIC_AUDIT.md`](qa/FULL_LOGIC_AUDIT.md), [`qa/BUSINESS_RULES_MATRIX.md`](qa/BUSINESS_RULES_MATRIX.md), [`qa/PRODUCT_DECISIONS.md`](qa/PRODUCT_DECISIONS.md) |
| Abnahme | [`qa/ABNAHME-CHECKLISTE.md`](qa/ABNAHME-CHECKLISTE.md) |
| Modul-Reviews | [`review-epic5-calendars.md`](review-epic5-calendars.md), [`review-epic8-upload.md`](review-epic8-upload.md), [`review-epic16-month-view.md`](review-epic16-month-view.md), [`review-todo-reminders.md`](review-todo-reminders.md), [`security-review-food-module.md`](security-review-food-module.md) |

## 10. Dieses Dokument pflegen

- Zahlen nur in Abschnitt 2 ändern, mit neuem Datum und aus dem angegebenen Befehl.
- Keine Dateilisten, Endpoint-Tabellen oder Testlisten ergänzen: Die liefern Dateisystem, OpenAPI und `pytest`.
- Eine neue Geschäftsregel gehört in Abschnitt 6, wenn sie weder aus dem Code-Docstring noch aus einem Fehlercode erkennbar ist. Erledigte Vorhaben kommen in `CHANGELOG.md`, nicht hierher.
- Vor jeder Änderung an „Offen“ und „Bekannte Einschränkungen“ die Aussage im Code prüfen. Eine erledigte oder falsche Zeile wird gestrichen, nicht durchgestrichen.
