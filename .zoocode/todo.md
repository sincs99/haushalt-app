# Epic 18: Einkaufsliste — „nach Geschäft" (Redesign + Verwaltung)

## Status: ✅ ABGESCHLOSSEN (2026-08-12)

---

## Erledigte Phasen

### Phase 1: Backend — Neue Endpoints ✅
- `GET /api/households/{hid}/shopping-items/stores` → distinct store-Werte
- `POST /api/households/{hid}/shopping-items/reassign-store` → Bulk-Rename/Dissolve
- Socket-Event: `shopping_items_bulk_updated`
- 9 Tests in `test_shopping_stores.py` — alle grün
- Bestehende 15 Tests in `test_shopping_scoping.py` — weiterhin grün

### Phase 2: Frontend — Repository + Store + Socket ✅
- `shoppingRepository.ts`: `fetchStores()` + `reassignStore()`
- `shopping.ts`: `stores`, `activeStoreFilter`, `fetchStores()`, `setStoreFilter()`, `reassignStore()`, `updateItem()`, `handleBulkUpdated()`
- `App.vue`: Socket-Event an 4 Stellen registriert + `fetchStores()` bei Join/Reconnect

### Phase 3: Frontend — UI Redesign ✅
- `ShoppingList.vue`: Store-Chips ersetzen PillTabs, Gruppierung nach Geschäft, Quick-Add mit Store-Übernahme, Kebab-Menü (Rename/Dissolve)
- `ShoppingItemEditSheet.vue`: Neue Komponente (Name, Menge, Geschäft, Abteilung)
- Item-Tap → Edit-Sheet (statt sofort Toggle)

### Phase 4: i18n ✅
- 15 neue Keys in DE + EN → 615 Keys total
- `npm run check:locales` grün, `npm run build` grün

### Phase 5a: Security Review ✅ BESTANDEN
- Keine kritischen/hohen Findings
- Multi-Tenant-Scoping korrekt, Input-Validierung OK, kein XSS
- Einzige Empfehlung: projektweites Rate-Limiting (bestehendes Thema)
- Dokument: `docs/security/epic18-shopping-stores-review.md`

### Phase 5b: Business Logic Review ✅
- 2 Findings identifiziert und behoben:
  1. **Merge-Warnung** → `confirmRename()` prüft jetzt ob Ziel-Store existiert
  2. **maxlength** → auf Rename-Input + Edit-Sheet Store-Input ergänzt
- Offener Punkt (nächster Sprint): Case-insensitive Store-Normalisierung

---

## Geänderte Dateien (Gesamtübersicht)

### Backend
| Datei | Änderung |
|-------|----------|
| `backend/app/routers/shopping.py` | 2 neue Endpoints + 2 Pydantic Schemas |
| `backend/tests/test_shopping_stores.py` | Neue Testdatei (9 Tests) |

### Frontend
| Datei | Änderung |
|-------|----------|
| `frontend/src/repositories/shoppingRepository.ts` | 2 neue Methoden |
| `frontend/src/stores/shopping.ts` | Neuer State + Actions + Socket-Handler |
| `frontend/src/App.vue` | Socket-Event + fetchStores + Cleanup |
| `frontend/src/components/ShoppingList.vue` | Hauptumbau (Store-Chips, Edit-Sheet, Kebab) |
| `frontend/src/components/ShoppingItemEditSheet.vue` | **Neue Datei** |
| `frontend/src/locales/de.json` | 15 neue Keys |
| `frontend/src/locales/en.json` | 15 neue Keys |

### Docs
| Datei | Änderung |
|-------|----------|
| `docs/security/epic18-shopping-stores-review.md` | Security Review |
| `docs/PROJECT-STATUS.md` | Epic 19 Eintrag + aktualisierte Tabellen |

---

## Offene Punkte (Follow-up)
- [ ] Case-insensitive Store-Normalisierung (Backend: `func.lower()` bei Vergleich/Distinct)
- [ ] Projektweites Rate-Limiting (Security-Empfehlung, nicht Epic-18-spezifisch)
