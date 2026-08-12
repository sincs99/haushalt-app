# Security Review — Epic 18: Shopping-Store Endpoints + Frontend

**Datum:** 2026-08-12  
**Reviewer:** AI Security Review (Claude)  
**Scope:** Neue Store-Endpoints, Frontend-Umbau Shopping-Modul  
**Gesamtbewertung: ✅ BESTANDEN — keine kritischen oder hohen Risiken gefunden**

---

## Geprüfte Dateien

| Datei | Typ | Änderung |
|-------|-----|----------|
| [`backend/app/routers/shopping.py`](../../backend/app/routers/shopping.py) | Backend | 2 neue Endpoints (Zeile 333 + 356), neues Schema `ReassignStoreRequest` |
| [`backend/tests/test_shopping_stores.py`](../../backend/tests/test_shopping_stores.py) | Tests | 9 neue Tests inkl. Cross-Tenant |
| [`frontend/src/repositories/shoppingRepository.ts`](../../frontend/src/repositories/shoppingRepository.ts) | Frontend | 2 neue API-Methoden (`fetchStores`, `reassignStore`) |
| [`frontend/src/stores/shopping.ts`](../../frontend/src/stores/shopping.ts) | Frontend | Neuer State (`stores`, `activeStoreFilter`), neue Actions + Socket-Handler |
| [`frontend/src/App.vue`](../../frontend/src/App.vue) | Frontend | Socket-Event `shopping_items_bulk_updated` registriert |
| [`frontend/src/components/ShoppingList.vue`](../../frontend/src/components/ShoppingList.vue) | Frontend | Store-Chips, Gruppierung, Kebab-Menü, Rename/Dissolve-Dialoge |
| [`frontend/src/components/ShoppingItemEditSheet.vue`](../../frontend/src/components/ShoppingItemEditSheet.vue) | Frontend | Neue Komponente: Store-Picker mit Chips + Freitext |

---

## Prüfergebnisse

### 1. Multi-Tenant-Scoping ✅ PASS

**Schweregrad:** Kein Finding

Beide neuen Endpoints verwenden [`verify_household_access`](../../backend/app/core/deps.py:32) als FastAPI-Dependency:

- **`GET /stores`** ([Zeile 333](../../backend/app/routers/shopping.py:333)): Filtert `ShoppingItem.household_id == household_id` — nur Items des eigenen Haushalts werden abgefragt.
- **`POST /reassign-store`** ([Zeile 356](../../backend/app/routers/shopping.py:356)): Filtert identisch `ShoppingItem.household_id == household_id` — Bulk-Updates sind strikt auf den eigenen Haushalt beschränkt.

Die Dependency [`verify_household_access`](../../backend/app/core/deps.py:32) prüft die `HouseholdMember`-Tabelle und wirft `403 Forbidden` bei fehlender Mitgliedschaft.

**Testabdeckung:**
- [`test_get_stores_cross_tenant_forbidden`](../../backend/tests/test_shopping_stores.py:69) — User A kann Stores von Household B nicht lesen → 403 ✅
- [`test_reassign_store_cross_tenant_forbidden`](../../backend/tests/test_shopping_stores.py:188) — User A kann in Household B nicht reassignen → 403 ✅

---

### 2. Input-Validierung & SQL-Injection ✅ PASS

**Schweregrad:** Kein Finding

Das Schema [`ReassignStoreRequest`](../../backend/app/routers/shopping.py:124) validiert sauber:

| Feld | Constraint | Validator |
|------|-----------|-----------|
| `from_store` | `min_length=1`, `max_length=100` | `strip_from_store` — trimmt Whitespace |
| `to_store` | `max_length=100`, nullable | `empty_string_to_none` — leerer String → `null` |

**SQL-Injection:** Ausgeschlossen. Alle Queries nutzen SQLAlchemy ORM mit parametrisierten Bindings. Es gibt keinerlei Raw-SQL oder String-Interpolation in Queries.

**Model-Konsistenz:** `ShoppingItem.store` ist `String(100)` ([Zeile 200](../../backend/app/models.py:200)), passend zu `max_length=100` im Schema.

**Testabdeckung:**
- [`test_reassign_store_empty_from_store`](../../backend/tests/test_shopping_stores.py:200) — leerer `from_store` → 422 Validation Error ✅

---

### 3. Bulk-Update-Risiko ✅ PASS (mit Hinweis)

**Schweregrad:** Gering (Info)

Der [`reassign_store`](../../backend/app/routers/shopping.py:356)-Endpoint lädt alle betroffenen Items via `.all()` in den Speicher und iteriert:

```python
affected_items = db.query(ShoppingItem).filter(
    ShoppingItem.household_id == household_id,
    ShoppingItem.store == body.from_store,
).all()

for item in affected_items:
    item.store = body.to_store
```

**Analyse:**
- ✅ Der Scope ist **strikt auf den Haushalt begrenzt** — keine Cross-Tenant-Updates möglich.
- ✅ Praktisch ist die Anzahl Items pro Haushalt klein (typisch <100).
- ℹ️ Bei extrem vielen Items (>1000) könnte der Memory-Footprint relevant werden. Für eine Haushalts-App ist dies unrealistisch.
- ℹ️ Ein `db.query(...).update({...})` wäre performanter als Einzelobjekt-Iteration, aber funktional korrekt.

**Empfehlung:** Keine Aktion erforderlich. Optional könnte ein Bulk-`UPDATE` statt ORM-Iteration verwendet werden, aber der Sicherheitsimpact ist null.

---

### 4. Socket-Event-Sicherheit ✅ PASS

**Schweregrad:** Kein Finding

Das Event `shopping_items_bulk_updated` wird korrekt behandelt:

**Backend:**
- [`emit_to_household_sync`](../../backend/app/socket_manager.py:142) emittiert an `room=f"household_{household_id}"` — nur Mitglieder des Haushalts empfangen das Event.
- Room-Beitritt ([`join_household`](../../backend/app/socket_manager.py:66)) prüft Membership via DB-Query — kein Beitritt ohne Mitgliedschaft möglich.

**Frontend:**
- Event-Registrierung in [`App.vue`](../../frontend/src/App.vue:164): `on('shopping_items_bulk_updated', shoppingStore.handleBulkUpdated)` ✅
- Event-Deregistrierung bei Cleanup ([Zeile 62](../../frontend/src/App.vue:62), [Zeile 270](../../frontend/src/App.vue:270)) ✅
- Event-Deregistrierung bei Household-Wechsel (Watch-Handler, [Zeile 62](../../frontend/src/App.vue:62)) ✅
- Dashboard-Invalidierung ebenfalls registriert ([Zeile 95](../../frontend/src/App.vue:95), [Zeile 199](../../frontend/src/App.vue:199)) ✅

**Handler-Sicherheit:**
[`handleBulkUpdated`](../../frontend/src/stores/shopping.ts:401) akzeptiert `{ item_ids: string[], changes: { store: string | null } }` und patcht nur lokale Items, die per `id` matchen. Kein DOM-Injection-Risiko.

---

### 5. Frontend XSS ✅ PASS

**Schweregrad:** Kein Finding

- **Kein `v-html`** in den gesamten Shopping-Komponenten (bestätigt per Regex-Suche über alle `.vue`-Dateien).
- Vue's Template-Syntax (`{{ }}`) escaped automatisch alle Werte.
- Store-Namen werden ausschliesslich via Safe-Interpolation gerendert:
  - [`ShoppingList.vue:321`](../../frontend/src/components/ShoppingList.vue:321): `{{ chip.label }}` ✅
  - [`ShoppingList.vue:342`](../../frontend/src/components/ShoppingList.vue:342): `{{ groupName }}` ✅
  - [`ShoppingList.vue:477`](../../frontend/src/components/ShoppingList.vue:477): `$t('shopping.dissolveConfirm', { store: dissolveTarget })` — i18n-Interpolation, escaped ✅
  - [`ShoppingItemEditSheet.vue:116`](../../frontend/src/components/ShoppingItemEditSheet.vue:116): `{{ s }}` ✅

---

### 6. Rate-Limiting ⚠️ Gering (vorbestehend)

**Schweregrad:** Gering (pre-existing, nicht neu in Epic 18)

Es existiert **kein Rate-Limiting** im gesamten Backend — weder global noch auf einzelnen Endpoints. Dies ist ein vorbestehendes Gap und wurde nicht durch Epic 18 eingeführt.

**Relevanz für Epic 18:**
- `POST /reassign-store` ist eine Bulk-Operation, die bei wiederholtem Aufruf viele DB-Updates erzeugen kann.
- Durch den Multi-Tenant-Scope ist der Blast Radius allerdings auf den eigenen Haushalt begrenzt.
- Ein DoS-Szenario müsste via wiederholte API-Calls erfolgen, was ohne Rate-Limiting möglich, aber kaum profitabel ist.

**Empfehlung (projektweite Verbesserung, nicht Epic-18-spezifisch):**
Mittelfristig ein globales Rate-Limiting einführen (z.B. `slowapi` oder Reverse-Proxy-Level), z.B. 60 Requests/Minute pro User. Dies betrifft alle Endpoints, nicht nur Shopping.

---

### 7. Zusätzliche Beobachtung: Whitespace-only `from_store` Edge Case

**Schweregrad:** Info

Pydantic v2 prüft `min_length=1` **vor** dem `field_validator`. Ein `from_store: "  "` (nur Leerzeichen, Länge 2) passiert die Längenprüfung, wird dann zu `""` gestrippt. Die resultierende DB-Query `ShoppingItem.store == ""` matcht keine Items, da leere Strings in Create/Update-Validatoren zu `None` normalisiert werden.

**Impact:** Null. Der Endpoint antwortet mit `{ "updated": 0 }`. Keine Datenkorruption, keine Ausnahme.

---

## Zusammenfassung

| # | Prüfpunkt | Bewertung | Schweregrad |
|---|-----------|-----------|-------------|
| 1 | Multi-Tenant-Scoping | ✅ PASS | — |
| 2 | Input-Validierung & SQL-Injection | ✅ PASS | — |
| 3 | Bulk-Update-Risiko | ✅ PASS | Info |
| 4 | Socket-Event-Sicherheit | ✅ PASS | — |
| 5 | Frontend XSS | ✅ PASS | — |
| 6 | Rate-Limiting | ⚠️ Hinweis | Gering (vorbestehend) |
| 7 | Whitespace Edge Case | ℹ️ Info | Info |

### Offene Empfehlungen

| Priorität | Empfehlung | Ticket? |
|-----------|-----------|---------|
| Gering | Globales Rate-Limiting einführen (projektweit, nicht Epic-18-spezifisch) | Eigenes Ticket |
| Info | Optional: `reassign_store` Bulk-UPDATE statt ORM-Iteration für Performance | Kein Ticket nötig |

---

**Fazit:** Die Epic-18-Implementierung ist sicherheitstechnisch sauber. Multi-Tenant-Isolation, Input-Validierung und Socket-Scoping sind korrekt umgesetzt und durch Tests abgedeckt. Es wurden keine neuen Sicherheitsrisiken eingeführt.
