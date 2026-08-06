# Design-Refresh — Haushalt-App Frontend

**Ziel:** Reiner Design-Refresh — keine neuen Features, keine Backend-Änderungen, keine Store-Logik-Änderungen (ausser wo explizit beschrieben).

**Regeln:**
- npm-Pakete IMMER mit expliziter Version, kompatibel zu `vue@^3.5.41`
- Jeder neue UI-String in `de.json` UND `en.json`
- Bestehende Funktionalität darf sich NICHT ändern
- Ausschliesslich Design-Tokens verwenden, keine hartcodierten Farben/Grössen
- Nach jedem Schritt: `npx vue-tsc --noEmit` und `npm run check:locales`
- Pro Aufgabe einzeln committen

---

## Aufgabe 1: Token-Refresh — warme Palette ✅ `8511609`
- [x] `theme.css`: Neutral-Palette von kühlem Blaugrau auf warme Stone-Töne umstellen
- [x] `theme.css`: Text-Tokens anpassen (`--color-text`, `--color-text-secondary`, `--color-text-muted`)
- [x] `theme.css`: Neue Tokens ergänzen (`--icon-size-sm/md/lg`, `--toast-duration`, `--radius-xl`, Avatar-Palette)
- [x] Alle Komponenten durchsuchen: hartcodierte Grau-Hex (#F9FAFB, #E5E7EB, #6B7280 etc.) auf Tokens umstellen
- [x] Border-Farben in Komponenten auf `--color-neutral-200` vereinheitlichen
- [x] `useToast.ts`: Default-Duration auf `var(--toast-duration)` / 4000ms Token verwenden
- [x] TypeCheck + Locale-Check + Commit

## Aufgabe 2: Lucide-Icons statt Emojis ✅ `15543db`
- [x] `npm i lucide-vue-next@0.454.0` (kompatibel mit Vue 3.5.x, Version prüfen)
- [x] `App.vue` Top-Bar: Emojis → Lucide-Icons (ShoppingCart, ListChecks, Wallet, Home etc.)
- [x] `App.vue` Tab-Bar: Emojis → Lucide-Icons, aktiv = Primary, inaktiv = --color-text-muted
- [x] `App.vue` Offline-Banner: 📡 → WifiOff
- [x] View-Titel: Emoji-Präfixe entfernen (ShoppingView, TodosView, ExpensesView, ChoresView)
- [x] Aktions-Buttons: ✕ → X, ✎ → Pencil, Hinzufügen → Plus (TodoList, ExpenseList, ExpensesView, ShoppingList)
- [x] `BaseEmptyState.vue`: icon-Prop von String auf Lucide-Komponente umbauen
- [x] Alle Aufrufer von BaseEmptyState anpassen (ShoppingList, TodoList, ExpenseList, ChoresView)
- [x] Toast-Typen: optionales Icon (CheckCircle2, AlertCircle, Info) in App.vue Toast-Rendering
- [x] i18n-Strings: Emojis entfernen (📋, ✓, 📅 etc. in de.json + en.json)
- [x] Aktive Tabs: Label mit `--font-weight-medium`, Icon+Label in Primary-Farbe
- [x] TypeCheck + Locale-Check + Commit

## Aufgabe 3: BaseAvatar mit deterministischen Farben ✅ `f1e8e4e`
- [x] `theme.css`: Avatar-Farbpaare (6er-Palette) als Tokens ergänzen
- [x] Neue Komponente `src/components/ui/BaseAvatar.vue` erstellen
- [x] `BalanceSummary.vue`: BaseAvatar statt Namenstext einsetzen
- [x] `ExpenseList.vue`: Avatar des Zahlers ergänzen
- [x] `ExpensesView.vue` Settlement-Liste: Avatare für from/to
- [x] `TodoList.vue`: Initialen-Chip durch BaseAvatar ersetzen
- [x] `ShoppingList.vue`: sm-Avatar des Erstellers (added_by_user_id vorhanden? → ja)
- [x] `App.vue` Top-Bar: eigener Avatar (md) statt Namenstext
- [x] TypeCheck + Locale-Check + Commit

## Aufgabe 4: Einkaufsliste — Erledigt-Sektion einklappbar ✅ `ea78e5c`
- [x] `ShoppingList.vue`: Erledigt-Sektion einklappbar mit Chevron-Icon
- [x] Default: eingeklappt wenn offene Items > 0
- [x] "Liste leeren"-Button in Sektions-Kopfzeile
- [x] Sanfte Transition beim Auf-/Zuklappen
- [x] i18n: Keys für "Liste leeren" in de.json + en.json
- [x] TypeCheck + Locale-Check + Commit

## Aufgabe 5: Undo-Toast statt confirm() ✅ `34a320e`
- [x] `useToast.ts`: Action-Parameter erweitern (label, onAction, 6000ms Dauer)
- [x] `App.vue`: Toast-Template um Action-Button ergänzen
- [x] Settlement-Löschen (`ExpensesView.vue`): confirm() → Optimistic Delete + Undo-Toast
- [x] Expense-Löschen (`ExpenseList.vue`): confirm() entfernen (war keins, aber Undo-Toast ergänzen)
- [x] Todo-Löschen (`TodoList.vue`): Undo-Toast ergänzen
- [x] Shopping-Item-Löschen (`ShoppingList.vue`): Undo-Toast ergänzen
- [x] "Liste leeren" (ShoppingList): Undo legt alle Items wieder an
- [x] ALLE verbleibenden confirm()-Aufrufe entfernen
- [x] i18n: `common.deleted`, `common.undo`, `common.listCleared` (DE + EN)
- [x] TypeCheck + Locale-Check + Commit

## Aufgabe 6: Skeleton-Loader ✅ `183aa97`
- [x] Neue Komponente `src/components/ui/BaseSkeleton.vue`
- [x] ShoppingList: Skeleton statt Spinner beim initialen Loading
- [x] TodoList: Skeleton statt Spinner beim initialen Loading
- [x] ExpenseList: Skeleton statt Spinner beim initialen Loading
- [x] Settlement-Liste (ExpensesView): Skeleton beim Loading
- [x] BaseSpinner bleibt für Button-Loading-States
- [x] TypeCheck + Locale-Check + Commit

## Aufgabe 7: Mobile-Feinschliff ✅ `c7ae1c7`
- [x] Tab-Bar: `padding-bottom: calc(... + env(safe-area-inset-bottom))` (bereits vorhanden ✓)
- [x] `index.html`: `viewport-fit=cover` prüfen (bereits vorhanden ✓)
- [x] Neuer Util `src/utils/dates.ts`: `formatDate()` + `formatDateShort()`, Locale aus i18n
- [x] Alle lokalen formatDate-Implementierungen ersetzen (TodoList, ExpenseList, ExpensesView, ChoresView)
- [x] Sync-Indikator: Top-Bar (Desktop) + Tab-Bar-Punkt (Mobile)
- [x] i18n: Status-Texte für Sync-Indikator (connected, reconnecting, offline) DE + EN
- [x] TypeCheck + Locale-Check + Commit

## Aufgabe 8: Selbstkontrolle ✅ (kein Commit nötig — 0 Fixes)
- [x] Grep: Kein Emoji mehr im UI (`src/`) — 0 Treffer ✅
- [x] Grep: Kein `confirm(` mehr in `src/` — 0 Treffer ✅
- [x] Grep: Keine hartcodierten Blaugrau-Hex in Komponenten — 0 Treffer ✅
- [x] `npm run check:locales` grün — 212 Keys synchron ✅
- [x] `npx vue-tsc --noEmit` grün ✅
- [x] `npm run build` erfolgreich ✅
- [x] Smoke-Test dokumentiert — Design-Refresh abgeschlossen

---

## NICHT in diesem Durchgang:
- ❌ Kein "Heute"-Dashboard-Tab
- ❌ Kein Dark Mode
- ❌ Keine Swipe-Gesten
- ❌ Keine Backend-/API-Änderungen
- ❌ Keine neuen Schriftarten
- ❌ Keine Änderungen an Login/Register-Views (ausser Token-Vererbung)
