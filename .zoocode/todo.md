# Business-Logik-Lücken: Währung, Admin-Rolle, Register-Flow

## Überblick
Drei Business-Logik-Lücken schliessen: erzwungene Haushalts-Währung, echte Admin-Rolle mit Verlassen/Entfernen, und Registrierungs-Flow für Eingeladene.

**Sequenzielle Abarbeitung** — nach jedem Backend-Schritt `pytest`, nach jedem Frontend-Schritt `npx vue-tsc --noEmit` + `npm run check:locales`. Git-Commit pro Aufgabe.

---

## Aufgabe 1: Haushalts-Währung erzwingen

### 1.1 Backend ✅ (erledigt 2026-08-06)
- [x] `Household.currency: Mapped[str]` (String(3), nullable=False, server_default="CHF") in `app/models.py`
- [x] Alembic-Migration `a194489b8f0e_add_household_currency.py` (SQLite-kompatibel)
- [x] Neuer Error-Code `CURRENCY_MISMATCH` in `app/core/error_codes.py`
- [x] `create_expense`: Currency-Check + Household-Default statt hartem "CHF"
- [x] `update_expense`: Currency-Check bei PATCH
- [x] `create_settlement`: Currency-Check + Household-Default
- [x] `HouseholdOut` in `app/routers/auth.py` um `currency` erweitern (Response von `/api/auth/me`)
- [x] Tests: 6 neue Tests in `tests/test_currency.py`, alle 125 Tests grün
- [x] `pytest backend/` ✅

> **API-Änderungen für Frontend:**
> - `GET /api/auth/me` → `households[].currency` ist jetzt im Response (String, z.B. "CHF")
> - `POST .../expenses/` → `currency` im Body ist jetzt **optional** (default=null → Server nutzt Household-Currency)
> - `POST .../settlements/` → `currency` im Body ist jetzt **optional** (default=null → Server nutzt Household-Currency)
> - Mismatch-Currency → `422` mit `detail.code = "CURRENCY_MISMATCH"`
> - `ExpenseCreate.currency` und `SettlementCreate.currency` akzeptieren weiterhin den Haushaltswert, lehnen aber Fremdwährungen ab

### 1.2 Frontend
- [ ] `HouseholdInfo` in `types/index.ts` um `currency: string` erweitern
- [ ] Currency-Felder aus Expense-/Settlement-Formularen entfernen (falls editierbar)
- [ ] Anzeige nutzt weiterhin Currency aus den Daten
- [ ] i18n: neue Strings in `de.json` + `en.json` für `CURRENCY_MISMATCH`
- [ ] `npx vue-tsc --noEmit` ✅
- [ ] `npm run check:locales` ✅
- [ ] **Git Commit: "feat: enforce household currency on expenses/settlements"**

---

## Aufgabe 2: Admin-Guard als Dependency ✅ (erledigt 2026-08-06)

### 2.1 Backend
- [x] Neuer Error-Code `ADMIN_REQUIRED` in `app/core/error_codes.py`
- [x] `verify_household_admin` in `app/core/deps.py`: baut auf `verify_household_access` auf, prüft `membership.role == "admin"`, sonst 403 ADMIN_REQUIRED
- [x] Test: `tests/test_admin_guard.py` – Admin passiert, Member bekommt 403 ADMIN_REQUIRED
- [x] `pytest backend/` ✅
- [x] i18n: `ADMIN_REQUIRED` in `de.json` + `en.json`
- [ ] **Git Commit: "feat: add verify_household_admin dependency"**

---

## Aufgabe 3: Haushalt erstellen, umbenennen, beitreten-Event ✅ (erledigt 2026-08-06)

### 3.1 Backend
- [x] Invite-Code-Generierung aus `auth.py` in gemeinsame Service-Funktion `app/services/invite_code.py` extrahieren
- [x] `auth.py` und neue Endpoints nutzen die gemeinsame Funktion
- [x] `POST /api/households` (201, nur Auth): Body `{name: str (1–100)}` → erstellt Haushalt + Membership role="admin". Response wie in `/me`.
- [x] `PATCH /api/households/{household_id}` (Admin): Body `{name}` → umbenennen. Socket-Event `household_updated` `{id, name}`
- [x] Bestehender `POST .../join`: Socket-Event `household_member_joined` `{display_name, user_id, role}` emittieren
- [x] `HouseholdMemberResponse` um `role` erweitert (GET /members gibt jetzt `role` zurück)
- [x] Mock-Patch für `emit_to_household_sync` in `conftest.py` um `app.routers.households` erweitern
- [x] Tests: 8 neue Tests in `tests/test_households.py`, alle 135 Tests grün
- [x] `pytest backend/` ✅
- [ ] **Git Commit: "feat: create/rename household endpoints + join event"**

> **API-Änderungen für Frontend:**
> - **NEU** `POST /api/households/` → Body `{"name": "..."}` → `201` mit `{id, name, role, currency}`
> - **NEU** `PATCH /api/households/{household_id}` → Body `{"name": "..."}` → `200` mit `{id, name}` (nur Admin)
> - `GET /api/households/{household_id}/members` → Response enthält jetzt **`role`** pro Mitglied (`"admin"` oder `"member"`)
> - `POST /api/households/join` → emittiert jetzt Socket-Event `household_member_joined` `{household_id, user_id, display_name, role}`
> - `PATCH /api/households/{household_id}` → emittiert Socket-Event `household_updated` `{id, name}`
> - Nicht-Admin auf PATCH → `403` mit `detail.code = "ADMIN_REQUIRED"`

---

## Aufgabe 4: Verlassen und Entfernen ✅ (Backend erledigt 2026-08-06)

### 4.1 Backend — Geschäftsregeln (nicht abweichen!)
- Verlassen IMMER erlaubt, auch mit Saldo ≠ 0
- Letztes Mitglied verlässt → Haushalt komplett löschen (CASCADE)
- Einziger Admin verlässt, Mitglieder bleiben → dienstältestes Mitglied (frühestes `joined_at`, Tiebreaker `user_id`) wird Admin
- Admin darf `role="member"` entfernen; andere Admins → 403 `CANNOT_REMOVE_ADMIN`
- Sich selbst entfernen → 422 (Verlassen-Endpoint nutzen)
- rotation_order NICHT bereinigen (Scheduler überspringt bereits)

### 4.2 Endpoints
- [x] Neuer Error-Code `CANNOT_REMOVE_ADMIN` + `CANNOT_REMOVE_SELF` in `error_codes.py`
- [x] `POST /api/households/{household_id}/leave` (204, jedes Mitglied): Event `household_member_left {household_id, user_id}`
- [x] `DELETE /api/households/{household_id}/members/{user_id}` (204, Admin): Event `household_member_removed {household_id, user_id}`
- [x] Socket-Hinweis als Kommentar im Router
- [x] Tests: 10 Tests in `tests/test_leave_remove.py`, alle 145 Tests grün
- [x] `pytest backend/` ✅
- [ ] **Git Commit: "feat: leave/remove household members with business rules"**

> **API-Änderungen für Frontend:**
> - **NEU** `POST /api/households/{household_id}/leave` → `204` (jedes Mitglied). Verlassen immer erlaubt, auch mit Saldo ≠ 0.
>   - Letztes Mitglied → Haushalt wird gelöscht (CASCADE)
>   - Einziger Admin → dienstältestes Mitglied (frühestes `joined_at`) wird automatisch Admin
>   - Socket-Event: `household_member_left` `{household_id, user_id}`
> - **NEU** `DELETE /api/households/{household_id}/members/{user_id}` → `204` (nur Admin)
>   - Nur Members entfernbar, nicht andere Admins → `403` mit `CANNOT_REMOVE_ADMIN`
>   - Sich selbst entfernen → `422` mit `CANNOT_REMOVE_SELF` (nutze `/leave`)
>   - Nicht-Mitglied als Ziel → `404` mit `NOT_HOUSEHOLD_MEMBER`
>   - Socket-Event: `household_member_removed` `{household_id, user_id}`
> - **i18n**: `CANNOT_REMOVE_ADMIN` + `CANNOT_REMOVE_SELF` in `de.json` + `en.json` hinzugefügt
> - Expenses/Balances bleiben nach Verlassen/Entfernen intakt (Ehemaliges-Mitglied-Muster)

---

## Aufgabe 5: Frontend — Mitglieder-Verwaltung + Selbst-Entfernung

### 5.1 Socket-Handler + Store
- [ ] `auth.ts` Store: Handler für `household_member_left`, `household_member_removed`, `household_member_joined`, `household_updated`
- [ ] Bindings in `App.vue` nach bestehendem Muster (on/off)
- [ ] Eigener User betroffen (left/removed): Haushaltsliste neu laden, auf ersten verbleibenden Haushalt wechseln, Socket reconnect; ohne Haushalt → "kein Haushalt"-Zustand
- [ ] Toast mit Info

### 5.2 HouseholdView.vue Sektionen
- [ ] Reihenfolge: Haushalt (Name editierbar für Admins), Mitglieder, Einladen, App (Sprache)
- [ ] Mitglieder-Liste: BaseAvatar (md) + Name + Badge "Admin"
- [ ] Für Admins: Entfernen-Aktion (Lucide UserMinus) mit Bestätigungs-Dialog

### 5.3 BaseDialog.vue
- [ ] Teleport, Overlay, Fokus-Falle, Esc schliesst
- [ ] Wiederverwendbar

### 5.4 Haushalt verlassen
- [ ] "Haushalt verlassen" als Danger-Aktion am Ende der Haushalt-Sektion
- [ ] Balances prüfen bei Saldo ≠ 0 → Dialog mit Saldo-Anzeige + Hinweis

### 5.5 i18n + Checks
- [ ] Alle neuen Strings in `de.json` + `en.json`
- [ ] `npx vue-tsc --noEmit` ✅
- [ ] `npm run check:locales` ✅
- [ ] **Git Commit: "feat: household member management UI + leave/remove"**

---

## Aufgabe 6: Onboarding-Zweig für Eingeladene

### 6.1 Backend ✅ (erledigt 2026-08-06)
- [x] `POST /api/auth/register`: Body-Umbau — `household_name: str | None` und `invite_code: str | None`
- [x] Pydantic `model_validator`: genau eines von beiden muss gesetzt sein (sonst 422)
- [x] invite_code-Pfad: Haushalt via Code suchen (404 INVITE_CODE_NOT_FOUND), Membership role="member"
- [x] household_name-Pfad: neuer Haushalt + Membership role="admin" (wie bisher)
- [x] 6 neue Tests in `tests/test_register.py`, alle Tests grün
- [x] `pytest backend/` ✅

> **API-Änderungen für Frontend:**
> - `POST /api/auth/register` → Body-Felder geändert:
>   - `household_name` ist jetzt **optional** (String | null)
>   - **NEU** `invite_code` (String | null) — Einladungscode eines bestehenden Haushalts
>   - **Genau eines** von `household_name` oder `invite_code` muss gesetzt sein (sonst `422`)
>   - Leere Strings (`""`) zählen als nicht gesetzt → `422`
> - Pfad A (household_name): Erstellt neuen Haushalt, User wird `admin` (Verhalten wie bisher)
> - Pfad B (invite_code): User tritt bestehendem Haushalt bei als `member`
>   - Ungültiger Code → `404` mit `detail.code = "INVITE_CODE_NOT_FOUND"`

### 6.2 Frontend
- [ ] `RegisterView.vue`: Umschalter (Tabs) zwischen "Neuen Haushalt gründen" und "Einladungscode"
- [ ] Query-Parameter `?code=XYZ` → automatisch Beitreten-Modus
- [ ] `auth.ts` Store: `register()`-Signatur erweitern
- [ ] `NoHouseholdView.vue`: zwei Karten — "Haushalt gründen" + "Mit Code beitreten"
- [ ] Router-Guard: authentifiziert + 0 Haushalte → `/no-household`
- [ ] HouseholdView: "Weiteren Haushalt gründen" Eintrag
- [ ] i18n
- [ ] `npx vue-tsc --noEmit` ✅
- [ ] `npm run check:locales` ✅
- [ ] **Git Commit: "feat: register with invite code + no-household flow"**

---

## Aufgabe 7: Einladung teilen

- [ ] HouseholdView, Sektion Einladen: Primär-Button "Einladung teilen" (Lucide Share2)
- [ ] `navigator.share()` mit i18n-Text inkl. Haushaltsname + Code
- [ ] Fallback: Clipboard + Toast
- [ ] Bestehender "Code kopieren" bleibt als sekundäre Aktion
- [ ] Kein Deep-Link, nur Name + Code. TODO-Kommentar für späteren Join-Link
- [ ] i18n DE+EN
- [ ] `npx vue-tsc --noEmit` ✅
- [ ] `npm run check:locales` ✅
- [ ] **Git Commit: "feat: share invite via Web Share API"**

---

## Aufgabe 8: Chores-Feinschliff

- [ ] `BaseEmptyState.vue`: optionalen Action-Slot erweitern
- [ ] ChoresView: Empty State der Wochenansicht bekommt CTA "Erstes Ämtli anlegen"
- [ ] Filter-Toggle "Nur meine" (Chip/Segmented, lokal): filtert Assignments auf eingeloggten User
- [ ] Überfällig-Badge respektiert den Filter
- [ ] i18n DE+EN
- [ ] `npx vue-tsc --noEmit` ✅
- [ ] `npm run check:locales` ✅
- [ ] **Git Commit: "feat: chores empty-state CTA + my-only filter"**

---

## Aufgabe 9: Abschluss

- [ ] `alembic upgrade head` gegen Docker-Postgres verifizieren
- [ ] `docs/PROJECT-STATUS.md` aktualisieren (Währungsregel, Rollen/Verlassen-Regeln, Register-Flow, Test-Count)
- [ ] Akzeptanz-Commit-Message dokumentieren: (a) Register mit Invite-Code, (b) Mitglied entfernen → NoHousehold, (c) EUR-Expense via API → 422, (d) Share-Button auf Mobile-Emulation
- [ ] **Git Commit: "docs: update project status with business rules + acceptance"**

---

## Ausdrücklich NICHT in diesem Durchgang
- Kein Multi-Currency
- Keine E-Mail-Einladungen / Join-Deep-Links
- Keine feingranularen Berechtigungen (nur admin/member)
- Kein manueller Admin-Transfer-Dialog
- Kein "Heute"-Dashboard
- Keine Änderung an rotation_order beim Entfernen
