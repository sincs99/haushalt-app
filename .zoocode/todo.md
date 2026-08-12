# Epic 13: Mobile-Eingabe-Fixes (Budget + Quick-Add-Buttons)

**Status:** ✅ Abgeschlossen
**Typ:** Reines Frontend-Epic – KEINE Backend-/Store-Änderungen  
**Erstellt:** 2026-08-12

---

## 13.1 – `type="number"` projektweit eliminieren

### Projektregel (ab sofort)
> Geld- und Zahlenfelder sind IMMER `type="text"` mit `inputmode="decimal"` (Dezimalwerte) bzw. `inputmode="numeric"` (Ganzzahlen). NIEMALS `type="number"`.

### Fundstellen (4 Stück)

| # | Datei | Zeile | Feld | Aktion |
|---|-------|-------|------|--------|
| 1 | `frontend/src/views/ExpensesView.vue` | ~315 | Budget-Inline-Edit | `type="text"` + `inputmode="decimal"`, `step`/`min` entfernen. `v-model` bleibt String (wird via `parseAmountToRappen` geparst). `@keyup.enter`/`@keyup.escape` und Save/Cancel-Buttons bleiben. |
| 2 | `frontend/src/views/ChoresView.vue` | ~497 | Monatstag (formDayOfMonth) | `type="text"` + `inputmode="numeric"`, `min`/`max` entfernen, `v-model.number` → `v-model` (String). parseInt-Validierung (1–31) im Submit-Handler, Fehlermeldung bei ungültigem Wert. |
| 3 | `frontend/src/views/PetsView.vue` | ~403 | Gewicht (formWeightGrams) | `type="text"` + `inputmode="decimal"`. `v-model` bleibt String. Parsing im Submit-Handler mit parseFloat + Validierung. |
| 4 | `frontend/src/views/PetDetailView.vue` | ~1105 | Gewicht (editFormWeightGrams) | Analog PetsView.vue. |

### Abnahmekriterium
```bash
grep -rn 'type="number"' frontend/src  # Muss LEER sein
```

---

## 13.2 – Quick-Add überall mit sichtbarem Plus-Button

### Referenz-Pattern: NotesView.vue (Zeile 150–165)
```vue
<form class="quick-add" @submit.prevent="handleQuickAdd">
  <BaseInput v-model="..." :placeholder="..." autocomplete="off" enterkeyhint="done" />
  <button type="submit" class="quick-add__btn" :disabled="!input.trim()" :aria-label="$t('common.add')">
    <PhPlus :size="20" weight="bold" />
  </button>
</form>
```

CSS (min. 44×44px Touch-Target, `var(--acc)` Background, `var(--radius-full)`):
```css
.quick-add { display: flex; gap: var(--space-2); align-items: flex-start; }
.quick-add :deep(.base-input) { flex: 1; }  /* oder .quick-add__input { flex: 1; } */
.quick-add__btn {
  flex-shrink: 0; width: 44px; height: 44px;
  border-radius: var(--radius-full); border: none;
  background: var(--acc); color: var(--card);
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; transition: opacity var(--transition-fast), transform var(--transition-fast);
}
.quick-add__btn:active { transform: scale(0.92); }
.quick-add__btn:disabled { opacity: 0.4; cursor: not-allowed; }
```

### Zu fixende Stellen (2 Stück)

| # | Datei | Zeile | Aktueller Stand | Aktion |
|---|-------|-------|-----------------|--------|
| 1 | `frontend/src/components/ShoppingList.vue` | ~163 | `<form>` mit `<input>`, KEIN Button | Plus-Button ergänzen, `PhPlus` importieren, `:disabled="!newItemName.trim()"`, Enter bleibt. CSS-Anpassung für flex-Layout. Button min 44×44px. |
| 2 | `frontend/src/components/TodoList.vue` | ~227 | `<form>` mit `<input>`, KEIN Button | Plus-Button ergänzen, `PhPlus` importieren, `:disabled="!newTodoTitle.trim()"`, Enter bleibt. CSS-Anpassung für flex-Layout. Button min 44×44px. |

### NICHT zu ändern (kein Quick-Add-Input-Pattern)
- `ExpenseList.vue` – hat bereits einen separaten "Add"-Dialog-Button (kein Inline-Input)
- `ShoppingView.vue:122` – Listenerstellung (kein Item-Quick-Add)
- `CalendarView`, `ChoresView`, `HouseholdView`, `NoHouseholdView` – komplexe Formulare
- `LoginView`, `RegisterView` – Auth-Formulare

---

## Locale-Pflege
Beide Locale-Dateien (`de.json`, `en.json`) müssen synchron bleiben. Falls neue Keys nötig (z.B. Validierungsmeldungen), in BEIDEN Dateien hinzufügen.

---

## Abnahme-Checkliste
- [ ] Budget auf Handy mit „50,00" UND „50.00" UND „50" setzbar
- [ ] Einkaufsliste: Artikel per Tap auf Plus hinzufügbar, ohne Tastatur-Enter
- [ ] Todo-Liste: Todo per Tap auf Plus hinzufügbar
- [ ] `npm run build` grün
- [ ] `npm run check:locales` grün
- [ ] `grep -rn 'type="number"' frontend/src` liefert keine Treffer
