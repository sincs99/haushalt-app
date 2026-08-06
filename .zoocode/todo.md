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

## Aufgabe 1: Token-Refresh — warme Palette
- [ ] `theme.css`: Neutral-Palette von kühlem Blaugrau auf warme Stone-Töne umstellen
- [ ] `theme.css`: Text-Tokens anpassen (`--color-text`, `--color-text-secondary`, `--color-text-muted`)
- [ ] `theme.css`: Neue Tokens ergänzen (`--icon-size-sm/md/lg`, `--toast-duration`, `--radius-xl`, Avatar-Palette)
- [ ] Alle Komponenten durchsuchen: hartcodierte Grau-Hex (#F9FAFB, #E5E7EB, #6B7280 etc.) auf Tokens umstellen
- [ ] Border-Farben in Komponenten auf `--color-neutral-200` vereinheitlichen
- [ ] `useToast.ts`: Default-Duration auf `var(--toast-duration)` / 4000ms Token verwenden
- [ ] TypeCheck + Locale-Check + Commit

## Aufgabe 2: Lucide-Icons statt Emojis
- [ ] `npm i lucide-vue-next@0.454.0` (kompatibel mit Vue 3.5.x, Version prüfen)
- [ ] `App.vue` Top-Bar: Emojis → Lucide-Icons (ShoppingCart, ListChecks, Wallet, Home etc.)
- [ ] `App.vue` Tab-Bar: Emojis → Lucide-Icons, aktiv = Primary, inaktiv = --color-text-muted
- [ ] `App.vue` Offline-Banner: 📡 → WifiOff
- [ ] View-Titel: Emoji-Präfixe entfernen (ShoppingView, TodosView, ExpensesView, ChoresView)
- [ ] Aktions-Buttons: ✕ → X, ✎ → Pencil, Hinzufügen → Plus (TodoList, ExpenseList, ExpensesView, ShoppingList)
- [ ] `BaseEmptyState.vue`: icon-Prop von String auf Lucide-Komponente umbauen
- [ ] Alle Aufrufer von BaseEmptyState anpassen (ShoppingList, TodoList, ExpenseList, ChoresView)
- [ ] Toast-Typen: optionales Icon (CheckCircle2, AlertCircle, Info) in App.vue Toast-Rendering
- [ ] i18n-Strings: Emojis entfernen (📋, ✓, 📅 etc. in de.json + en.json)
- [ ] Aktive Tabs: Label mit `--font-weight-medium`, Icon+Label in Primary-Farbe
- [ ] TypeCheck + Locale-Check + Commit

## Aufgabe 3: BaseAvatar mit deterministischen Farben
- [ ] `theme.css`: Avatar-Farbpaare (6er-Palette) als Tokens ergänzen
- [ ] Neue Komponente `src/components/ui/BaseAvatar.vue` erstellen
- [ ] `BalanceSummary.vue`: BaseAvatar statt Namenstext einsetzen
- [ ] `ExpenseList.vue`: Avatar des Zahlers ergänzen
- [ ] `ExpensesView.vue` Settlement-Liste: Avatare für from/to
- [ ] `TodoList.vue`: Initialen-Chip durch BaseAvatar ersetzen
- [ ] `ShoppingList.vue`: sm-Avatar des Erstellers (added_by_user_id vorhanden? → ja)
- [ ] `App.vue` Top-Bar: eigener Avatar (md) statt Namenstext
- [ ] TypeCheck + Locale-Check + Commit

## Aufgabe 4: Einkaufsliste — Erledigt-Sektion einklappbar
- [ ] `ShoppingList.vue`: Erledigt-Sektion einklappbar mit Chevron-Icon
- [ ] Default: eingeklappt wenn offene Items > 0
- [ ] "Liste leeren"-Button in Sektions-Kopfzeile
- [ ] Sanfte Transition beim Auf-/Zuklappen
- [ ] i18n: Keys für "Liste leeren" in de.json + en.json
- [ ] TypeCheck + Locale-Check + Commit

## Aufgabe 5: Undo-Toast statt confirm()
- [ ] `useToast.ts`: Action-Parameter erweitern (label, onAction, 6000ms Dauer)
- [ ] `App.vue`: Toast-Template um Action-Button ergänzen
- [ ] Settlement-Löschen (`ExpensesView.vue`): confirm() → Optimistic Delete + Undo-Toast
- [ ] Expense-Löschen (`ExpenseList.vue`): confirm() entfernen (war keins, aber Undo-Toast ergänzen)
- [ ] Todo-Löschen (`TodoList.vue`): Undo-Toast ergänzen
- [ ] Shopping-Item-Löschen (`ShoppingList.vue`): Undo-Toast ergänzen
- [ ] "Liste leeren" (ShoppingList): Undo legt alle Items wieder an
- [ ] ALLE verbleibenden confirm()-Aufrufe entfernen
- [ ] i18n: `common.deleted`, `common.undo`, `common.listCleared` (DE + EN)
- [ ] TypeCheck + Locale-Check + Commit

## Aufgabe 6: Skeleton-Loader
- [ ] Neue Komponente `src/components/ui/BaseSkeleton.vue`
- [ ] ShoppingList: Skeleton statt Spinner beim initialen Loading
- [ ] TodoList: Skeleton statt Spinner beim initialen Loading
- [ ] ExpenseList: Skeleton statt Spinner beim initialen Loading
- [ ] Settlement-Liste (ExpensesView): Skeleton beim Loading
- [ ] BaseSpinner bleibt für Button-Loading-States
- [ ] TypeCheck + Locale-Check + Commit

## Aufgabe 7: Mobile-Feinschliff
- [ ] Tab-Bar: `padding-bottom: calc(... + env(safe-area-inset-bottom))` (bereits vorhanden ✓)
- [ ] `index.html`: `viewport-fit=cover` prüfen (bereits vorhanden ✓)
- [ ] Neuer Util `src/utils/dates.ts`: `formatDate()` + `formatDateShort()`, Locale aus i18n
- [ ] Alle lokalen formatDate-Implementierungen ersetzen (TodoList, ExpenseList, ExpensesView, ChoresView)
- [ ] Sync-Indikator: Top-Bar (Desktop) + Tab-Bar-Punkt (Mobile)
- [ ] i18n: Status-Texte für Sync-Indikator (connected, reconnecting, offline) DE + EN
- [ ] TypeCheck + Locale-Check + Commit

## Aufgabe 8: Selbstkontrolle
- [ ] Grep: Kein Emoji mehr im UI (`src/`)
- [ ] Grep: Kein `confirm(` mehr in `src/`
- [ ] Grep: Keine hartcodierten Blaugrau-Hex (#F9FAFB, #E5E7EB, #6B7280 etc.) in Komponenten
- [ ] `npm run check:locales` grün
- [ ] `npx vue-tsc --noEmit` grün
- [ ] `npm run build` läuft durch
- [ ] Finaler Commit mit Smoke-Test-Notiz

---

## NICHT in diesem Durchgang:
- ❌ Kein "Heute"-Dashboard-Tab
- ❌ Kein Dark Mode
- ❌ Keine Swipe-Gesten
- ❌ Keine Backend-/API-Änderungen
- ❌ Keine neuen Schriftarten
- ❌ Keine Änderungen an Login/Register-Views (ausser Token-Vererbung)
