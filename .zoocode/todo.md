# Design-Foundation Teil 3 — UI auf Design-System bringen

## Übersicht
Bestehende UI-Komponenten und Views auf das Design-System aus den Projekt-Rules umstellen.
Kein Backend, keine Funktionsänderungen, reine Optik + Icon-Migration.

## Dateien

### Neue Dateien
- `frontend/src/utils/memberColor.ts` — Deterministisches User→Farbe-Mapping
- `frontend/src/components/ui/BaseCheckCircle.vue` — Runde Checkbox nach Design-System
- `frontend/src/components/ui/BasePillTabs.vue` — Generische Pill-Filterleiste

### Geänderte Dateien (UI-Komponenten)
- `frontend/src/assets/theme.css` — Neue Tokens ergänzen
- `frontend/src/components/ui/BaseCard.vue` — Radius 20px, direkte Tokens
- `frontend/src/components/ui/BaseButton.vue` — Primary=acc, Secondary=chip, Radius-Update
- `frontend/src/components/ui/BaseAvatar.vue` — memberColor.ts nutzen
- `frontend/src/components/ui/BaseInput.vue` — Tokens ersetzen (neutral→line/chip)
- `frontend/src/components/ui/BaseDialog.vue` — Lucide→Phosphor, Tokens
- `frontend/src/components/ui/BaseEmptyState.vue` — Lucide→Phosphor
- `frontend/src/components/ui/BaseSkeleton.vue` — Tokens ersetzen
- `frontend/src/components/ui/BaseSpinner.vue` — Tokens ersetzen

### Geänderte Dateien (Lucide→Phosphor + CheckCircle + Titel)
- `frontend/src/App.vue` — 10 Icons migrieren, Titel-Font
- `frontend/src/components/TheBottomNav.vue` — 5 Icons migrieren
- `frontend/src/components/MoreSheet.vue` — 5 Icons migrieren
- `frontend/src/components/ShoppingList.vue` — Icons + BaseCheckCircle
- `frontend/src/components/TodoList.vue` — Icons + BaseCheckCircle
- `frontend/src/components/ExpenseList.vue` — 2 Icons migrieren
- `frontend/src/views/ChoresView.vue` — 4 Icons + BasePillTabs + Titel-Font
- `frontend/src/views/ExpensesView.vue` — 1 Icon + Titel-Font
- `frontend/src/views/HouseholdView.vue` — 4 Icons + Titel-Font
- `frontend/src/views/LoginView.vue` — 1 Icon + Titel-Font
- `frontend/src/views/RegisterView.vue` — 1 Icon + Titel-Font
- `frontend/src/views/NoHouseholdView.vue` — 2 Icons + Titel-Font
- `frontend/src/views/DashboardView.vue` — 1 Icon
- `frontend/src/views/CalendarView.vue` — 1 Icon
- `frontend/src/views/ShoppingView.vue` — Titel-Font
- `frontend/src/views/TodosView.vue` — Titel-Font

### Package-Änderung
- `frontend/package.json` — `lucide-vue-next` entfernen (npm uninstall)

### Nicht anfassen
- Backend (gesamter `backend/` Ordner)
- Stores, Repositories, Composables, Types (keine Funktionsänderungen)
- i18n-Dateien (keine neuen Keys nötig, außer evtl. für PillTabs-Labels)
- `frontend/src/components/BalanceSummary.vue` (kein Lucide, keine Token-Probleme)
- `frontend/src/components/ExpenseFormDialog.vue` (kein Lucide, keine Token-Probleme)

---

## Detailspezifikation

### Phase 1: Theme-Tokens ergänzen

In `frontend/src/assets/theme.css` `:root` hinzufügen:
```css
--radius-card: 20px;    /* Karten */
--radius-btn: 12px;     /* Buttons */
--radius-dialog: 24px;  /* Dialoge/Sheets */
```

### Phase 2: utils/memberColor.ts

```ts
/**
 * Deterministisches Mapping User-ID → CSS-Farb-Variable.
 * Derselbe User hat überall dieselbe Farbe.
 */
const MEMBER_COLORS = [
  'var(--p1)',       // Teal
  'var(--p2)',       // Rosa
  '#94798C',         // Mauve
  '#8A8272',         // Olive
  'var(--acc)',       // Braun/Gold
  'var(--ok)',        // Grün
] as const

export function getMemberColor(userId: string): string {
  let hash = 0
  for (const ch of userId) {
    hash += ch.charCodeAt(0)
  }
  return MEMBER_COLORS[hash % MEMBER_COLORS.length]
}
```

### Phase 3: UI-Komponenten-Updates

#### BaseCard.vue
- `border-radius: var(--radius-md)` → `var(--radius-card)`
- `background: var(--color-surface)` → `var(--card)` (direkt, nicht Alias)

#### BaseButton.vue
- `border-radius: var(--radius-sm)` → `var(--radius-btn)`
- **Primary**: `background: var(--acc)`, `color: #fff` (Light) / `color: var(--card)` (Dark) → einfach `color: #FBF8F3` oder besser `color: var(--card)`
- **Primary hover**: `filter: brightness(1.08)` statt alter Variable
- **Secondary**: `background: var(--chip)`, `color: var(--ink)`, `border-color: transparent`
- **Secondary hover**: `filter: brightness(0.96)`
- **Ghost**: `color: var(--acc)`, hover `background: var(--acc-soft)`
- **Danger**: bleibt (--color-danger)
- Alle `var(--color-neutral-*)` entfernen (existieren nicht im Theme)
- Focus-Ring: `outline-color: var(--acc)` statt `var(--color-primary)`

#### BaseInput.vue
- `border: 1px solid var(--color-neutral-300)` → `border: 1px solid var(--line-strong)`
- `background-color: var(--color-surface)` → `var(--card)`
- `:focus border-color` → `var(--acc)`
- `:focus box-shadow` → `0 0 0 3px var(--acc-soft)`
- Error: `--color-danger-light` → `var(--acc-soft)` (danger bleibt)
- Disabled bg `var(--color-neutral-100)` → `var(--chip)`
- `border-radius: var(--radius-sm)` → `var(--radius-btn)` (12px passend für Inputs)

#### BaseDialog.vue
- `import { X } from 'lucide-vue-next'` → `import { PhX } from '@phosphor-icons/vue'`
- Template: `<X :size="18" />` → `<PhX :size="18" />`
- `.dialog-panel border-radius: var(--radius-lg)` → `var(--radius-dialog)`
- `.dialog-panel box-shadow: var(--shadow-lg)` → `var(--shadow-overlay)`
- `.dialog-panel background: var(--color-surface)` → `var(--card)`
- `.dialog-header border-bottom: 1px solid var(--color-neutral-200)` → `var(--line)`
- `.dialog-footer border-top: 1px solid var(--color-neutral-200)` → `var(--line)`
- `.dialog-close:hover background: var(--color-neutral-100)` → `var(--chip)`
- `var(--space-5)` existiert nicht → `var(--space-6)` (24px) verwenden

#### BaseEmptyState.vue
- `import { Package } from 'lucide-vue-next'` → `import { PhPackage } from '@phosphor-icons/vue'`
- Default icon: `Package` → `PhPackage`
- `color: var(--color-text-muted)` → `var(--sub)`

#### BaseSkeleton.vue
- `background: var(--color-neutral-100)` → `var(--chip)`

#### BaseSpinner.vue
- `border-color: var(--color-neutral-300)` → `var(--line-strong)`
- `border-top-color: var(--color-primary)` → `var(--acc)`

### Phase 4: BaseCheckCircle.vue (NEU)

```
Props: checked: boolean
Emits: toggle
```

Design:
- **Unchecked**: 22×22px Kreis, border 2px `var(--line-strong)`, transparent fill
- **Checked**: 22×22px Kreis, `var(--ok)` Hintergrund, weisser PhCheck bold-Icon (12px)
- Transition 150ms ease
- `cursor: pointer`, `flex-shrink: 0`

Integration **ShoppingList.vue**:
- Ersetze `<input type="checkbox" ...>` in Item-Zeilen durch `<BaseCheckCircle :checked="item.is_checked" @toggle="handleToggle(item.id)" />`
- `.item-row--checked .item-row__name`: `text-decoration: line-through; color: var(--sub)` (statt `opacity: 0.55`)
- Entferne `.item-row__check` wrapper und `.item-row__checkbox` Styling

Integration **TodoList.vue**:
- Ersetze `<input type="checkbox" ...>` durch `<BaseCheckCircle :checked="todo.is_done" @toggle="handleToggle(todo.id)" />`
- `.todo-row--done .todo-row__name`: `text-decoration: line-through; color: var(--sub)` (statt `opacity: 0.55`)

### Phase 5: BasePillTabs.vue (NEU)

```ts
Props:
  tabs: Array<{ key: string; label: string }>
  modelValue: string   // aktiver key

Emits:
  'update:modelValue': [key: string]
```

Design:
- Horizontal scrollbar (flex, gap 8px, `overflow-x: auto`, `-webkit-overflow-scrolling: touch`)
- Jede Pill: `padding: 6px 16px`, `border-radius: var(--radius-full)`, `font-size: var(--text-sm)`, `font-weight: 600`, `white-space: nowrap`, `cursor: pointer`, `transition: all 150ms`
- **Aktiv**: `background: var(--ink)`, `color: var(--card)`
- **Inaktiv**: `background: var(--chip)`, `color: var(--ink)`
- Keine native `<button>`-Border

Exemplarische Nutzung in **ChoresView.vue**:
- Ersetze den `showOnlyMine`-Toggle durch BasePillTabs mit 2 Tabs: "Alle" / "Meine"
- i18n-Keys: `chores.filterAll` (de: "Alle", en: "All") / `chores.filterMine` (de: "Meine", en: "Mine") → **in de.json + en.json** ergänzen

### Phase 6: Lucide → Phosphor Icon-Mapping

**WICHTIG**: Phosphor-Icons aus `@phosphor-icons/vue` importieren. Namensschema: `Ph` + Name.
Standard-Gewicht: regular. Aktive Nav / Status: `weight="fill"`. Checkmarks: `weight="bold"`.

Vollständige Mapping-Tabelle:

| Lucide Icon | Phosphor Icon | Import-Name | Dateien |
|---|---|---|---|
| `X` | X | `PhX` | BaseDialog, ShoppingList, TodoList, ExpenseList, ExpensesView, ChoresView |
| `Package` | Package | `PhPackage` | BaseEmptyState |
| `ShoppingCart` | ShoppingCart | `PhShoppingCart` | App.vue, TheBottomNav, ShoppingList |
| `ListChecks` | ListChecks | `PhListChecks` | App.vue, TheBottomNav, TodoList |
| `Wallet` | Wallet | `PhWallet` | App.vue, MoreSheet |
| `Home` | House | `PhHouse` | App.vue, TheBottomNav, LoginView, RegisterView, NoHouseholdView |
| `Brush` | Broom | `PhBroom` | App.vue, ChoresView |
| `CalendarDays` | CalendarBlank | `PhCalendarBlank` | App.vue, TheBottomNav, CalendarView |
| `WifiOff` | WifiSlash | `PhWifiSlash` | App.vue |
| `CheckCircle2` | CheckCircle | `PhCheckCircle` | App.vue |
| `AlertCircle` | WarningCircle | `PhWarningCircle` | App.vue |
| `Info` | Info | `PhInfo` | App.vue |
| `MoreHorizontal` | DotsThree | `PhDotsThree` | TheBottomNav |
| `Cat` | Cat | `PhCat` | MoreSheet |
| `UtensilsCrossed` | ForkKnife | `PhForkKnife` | MoreSheet |
| `StickyNote` | Note | `PhNote` | MoreSheet |
| `Settings` | Gear | `PhGear` | MoreSheet |
| `Pencil` | PencilSimple | `PhPencilSimple` | TodoList, ChoresView |
| `ChevronDown` | CaretDown | `PhCaretDown` | ShoppingList |
| `Receipt` | Receipt | `PhReceipt` | ExpenseList |
| `CalendarCheck` | CalendarCheck | `PhCalendarCheck` | ChoresView |
| `UserMinus` | UserMinus | `PhUserMinus` | HouseholdView |
| `LogOut` | SignOut | `PhSignOut` | HouseholdView |
| `Plus` | Plus | `PhPlus` | HouseholdView |
| `Share2` | ShareNetwork | `PhShareNetwork` | HouseholdView |
| `Construction` | Wrench | `PhWrench` | DashboardView |
| `Users` | Users | `PhUsers` | NoHouseholdView |

**Icon-Size-Mapping**: Lucide `:size="N"` → Phosphor `:size="N"` (gleich).

**Nach Migration**: `npm uninstall lucide-vue-next` aus `frontend/`.

### Phase 7: Abschnittstitel → font-display

Alle `.view-title`, `.section-title`, `.auth-title`, `.card-title`, `.dialog-title`, `.no-household-title` Klassen:
```css
font-family: var(--font-display);
font-weight: var(--font-weight-semibold); /* 600 */
```

Betrifft Dateien mit `<style scoped>`:
- ShoppingView, TodosView, ExpensesView, ChoresView, HouseholdView, LoginView, RegisterView, NoHouseholdView
- BaseDialog.vue (`.dialog-title`)
- ExpenseList.vue und BalanceSummary.vue (falls `.section-title` vorhanden)

### Phase 8: Bereinigung alte Alias-Variablen in theme.css

In `theme.css` die alten Alias-Mappings (`--color-primary`, `--color-surface`, etc.) BEIBEHALTEN für Abwärtskompatibilität, aber in den aktualisierten Komponenten die neuen direkten Tokens verwenden.

---

## Nicht anfassen / Warnung
- `<script>` in App.vue (Zeilen 1-173): Socket-Logik → NICHT VERÄNDERN, nur Imports ändern
- Stores, Repositories, Types → keine Änderungen
- Backend → komplett unberührt
- Bestehende Funktionalität → keine Regression, nur visuelle Änderungen

## Abnahmekriterien
- [x] Alle Views im neuen Look (Karten 20px radius, Buttons mit acc/chip, runde Checkboxen)
- [x] BaseCheckCircle in Shopping + Todos
- [x] BasePillTabs bereitgestellt + exemplarisch in ChoresView
- [x] Kein Lucide-Import mehr in KEINER Datei
- [x] `lucide-vue-next` nicht mehr in package.json
- [x] `npm run typecheck` grün
- [x] `npm run build` grün
- [x] Dark Mode funktioniert weiterhin korrekt
