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

## Aufgabe 2: Admin-Guard als Dependency

### 2.1 Backend
- [ ] Neuer Error-Code `ADMIN_REQUIRED` in `app/core/error_codes.py`
- [ ] `verify_household_admin` in `app/core/deps.py`: baut auf `verify_household_access` auf, prüft `membership.role == "admin"`, sonst 403 ADMIN_REQUIRED
- [ ] Test: Nicht-Admin auf Admin-Endpoint → 403 ADMIN_REQUIRED
- [ ] `pytest backend/` ✅
- [ ] i18n: `ADMIN_REQUIRED` in `de.json` + `en.json`
- [ ] **Git Commit: "feat: add verify_household_admin dependency"**

---

## Aufgabe 3: Haushalt erstellen, umbenennen, beitreten-Event

### 3.1 Backend
- [ ] Invite-Code-Generierung aus `auth.py` in gemeinsame Service-Funktion `app/services/invite_code.py` extrahieren
- [ ] `auth.py` und neue Endpoints nutzen die gemeinsame Funktion
- [ ] `POST /api/households` (201, nur Auth): Body `{name: str (1–100)}` → erstellt Haushalt + Membership role="admin". Response wie in `/me`.
- [ ] `PATCH /api/households/{household_id}` (Admin): Body `{name}` → umbenennen. Socket-Event `household_updated` `{id, name}`
- [ ] Bestehender `POST .../join`: Socket-Event `household_member_joined` `{display_name, user_id, role}` emittieren
- [ ] Mock-Patch für `emit_to_household_sync` in `conftest.py` um `app.routers.households` erweitern
- [ ] Tests: create → Ersteller ist admin; rename als Nicht-Admin → 403; Events emittiert
- [ ] `pytest backend/` ✅
- [ ] **Git Commit: "feat: create/rename household endpoints + join event"**

---

## Aufgabe 4: Verlassen und Entfernen

### 4.1 Backend — Geschäftsregeln (nicht abweichen!)
- Verlassen IMMER erlaubt, auch mit Saldo ≠ 0
- Letztes Mitglied verlässt → Haushalt komplett löschen (CASCADE)
- Einziger Admin verlässt, Mitglieder bleiben → dienstältestes Mitglied (frühestes `joined_at`, Tiebreaker `user_id`) wird Admin
- Admin darf `role="member"` entfernen; andere Admins → 403 `CANNOT_REMOVE_ADMIN`
- Sich selbst entfernen → 422 (Verlassen-Endpoint nutzen)
- rotation_order NICHT bereinigen (Scheduler überspringt bereits)

### 4.2 Endpoints
- [ ] Neuer Error-Code `CANNOT_REMOVE_ADMIN` in `error_codes.py`
- [ ] `POST /api/households/{household_id}/leave` (204, jedes Mitglied): Regeln oben. Event `household_member_left {household_id, user_id}`
- [ ] `DELETE /api/households/{household_id}/members/{user_id}` (204, Admin): Regeln oben. Event `household_member_removed {household_id, user_id}`
- [ ] Socket-Hinweis als Kommentar im Router
- [ ] Tests:
  - leave normal
  - letzter Admin mit Auto-Promotion (genau das dienstälteste Mitglied wird Admin)
  - letztes Mitglied löscht Haushalt inkl. Kaskade (Expenses etc. weg)
  - remove als Member → 403
  - Admin entfernt Admin → 403 CANNOT_REMOVE_ADMIN
  - Entfernter bekommt auf alle Endpoints 403
  - Balances zeigen Ex-Mitglied weiterhin korrekt
- [ ] `pytest backend/` ✅
- [ ] **Git Commit: "feat: leave/remove household members with business rules"**

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

### 6.1 Backend
- [ ] `POST /api/auth/register`: Body-Umbau — `household_name: str | None` und `invite_code: str | None`
- [ ] Pydantic-Validator: genau eines von beiden muss gesetzt sein (sonst 422)
- [ ] invite_code-Pfad: Haushalt via Code suchen (404 INVITE_CODE_NOT_FOUND), Membership role="member"
- [ ] Bestehende Tests anpassen + neue: Register mit Code, ungültiger Code, beidem/keinem → 422
- [ ] `pytest backend/` ✅

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
