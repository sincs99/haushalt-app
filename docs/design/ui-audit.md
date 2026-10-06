# UI-Design-Audit

Stand: 2026-10-06 · Branch `claude/ui-design-audit` · Basis: `master` @ `d41ab20`

Prüfung aus Sicht eines UI-Designers: Tokens, Typografie, Komponenten, Icons, Dark Mode, Kontraste, Bewegung, Listen-Anatomie über alle Module.
Grundlage sind `frontend/src/assets/theme.css`, `components/ui/*`, alle Views/Komponenten (≈ 20 800 Zeilen `.vue`) und Vorher/Nachher-Screenshots (Playwright, 390 × 844, Light und Dark; liegen lokal unter `frontend/qa/ui/`, nicht im Repository).

Token-Referenz: [`design-tokens.md`](design-tokens.md).

**Schwere:** 🔴 hoch (sichtbarer Fehler, Barriere) · 🟠 mittel (deutliche Inkonsistenz) · 🟡 gering (Feinschliff, Wartbarkeit)
**Status:** ✅ behoben · ◐ teilweise · ⏸ offen/dokumentiert · ➜ anderer Branch

Abgrenzung: Layout-Fehler (Überlappungen, abgeschnittene Texte auf Mobile) → `claude/mobile-layout-fixes`; Verhalten und Texte von Feedback/Toasts → `claude/ux-feedback`. Dieser Branch ändert nur Styles, Tokens und Basis-Komponenten. In den Views werden nur Klassen, Token-Referenzen, Icon-Grössen und Komponenten getauscht; Templates werden nicht umgebaut.

---

## Zusammenfassung

| Bereich | 🔴 | 🟠 | 🟡 | Ergebnis |
|---|---|---|---|---|
| 1 Design-Tokens | 2 | 3 | 4 | Alle Tokens definiert; keine Hex-/rgba-Werte mehr in Komponenten (zwei bewusste Ausnahmen) |
| 2 Typografie | – | 2 | 3 | Skala um `--text-md` (18 px) ergänzt; Titel einheitlich Quicksand |
| 3 Komponenten | 1 | 3 | 3 | `BaseCard` mit `#header`-Slot, einheitliche Zustände der Basis-Komponenten |
| 4 Icons | – | 2 | 3 | Skala 12/16/20/24/32/48; Emoji-Icons ersetzt |
| 5 Dark Mode | 2 | 1 | 1 | Vollständig; hardcodierte helle Flächen entfernt |
| 6 Kontraste | 3 | 3 | – | Alle geprüften Text-/Badge-Paare ≥ AA |
| 7 Bewegung | – | 1 | 2 | Dauer- und Easing-Tokens, `prefers-reduced-motion` greift überall |
| 8 Listen-Anatomie | – | 2 | 2 | Einheitliche Item-Tokens; Struktur-Unterschiede dokumentiert |

---

## 1. Design-Tokens

Inventar vor dem Audit: 13 Palette-Tokens, 14 Aliase, 5 Schriftgrössen, 6 Abstände, 8 Radien, 2 Schatten, 2 Transitions, 3 Icon-Grössen. **Keine** Z-Index-, Dauer-, Easing-, Overlay- oder „on-color“-Tokens.

| # | Schwere | Befund | Fix | Status |
|---|---|---|---|---|
| T1 | 🔴 | **14 verwendete, aber nirgends definierte Tokens** (`--color-neutral-50/100/200/300/400/900`, `--border`, `--ink-secondary`, `--surface`, `--green`, `--warn`, `--shadow-sm`, `--space-0-5`, `--space-5`) in 15 Dateien, ≈ 55 Stellen. Ohne Fallback wird die Eigenschaft ungültig: Trennlinien in Haushalt, Putzplan, Ausgaben, Saldo und Top-Bar fehlen, Hover-Flächen bleiben transparent, der Text im Offline-Banner erbt eine zufällige Farbe. | Durch semantische Tokens ersetzt (`neutral-200` → `--line`, `neutral-300` → `--line-strong`, `neutral-50/100` → `--color-surface-subtle`/`--chip`, `neutral-900` → `--color-on-warning` usw.); `--space-0-5`, `--space-5`, `--shadow-sm` ergänzt. Prüfskript: kein `var(--…)` ohne Definition. | ✅ |
| T2 | 🔴 | Hardcodierte helle Flächen: `#FFF5F5` (überfälliges Todo, Putzplan-Hover, Lösch-Bestätigung), `#FECACA` (Auth-Fehlerrahmen). Im Dark Mode leuchtende rosa Flächen mit hellem Text. | `--color-danger-soft` / `--color-danger-border` mit Dark-Werten | ✅ |
| T3 | 🟠 | Fremde Farben ausserhalb der Palette: `#C75B39` (überfällige Tierpflege), Indigo-`rgba(99,102,241,…)` als Fallback in Essens-Abstimmungen, `#22c55e`, `#ef4444`, `#f59e0b`, `#c0392b` als Fallbacks. | Auf `--color-danger`, `--acc-soft`, `--ok` umgestellt, Fallbacks entfernt | ✅ |
| T4 | 🟠 | `color: #fff` auf farbigen Flächen (15×), u. a. FAB, Badges, Kamera-Buttons, Check-Kreis, Avatar. Im Dark Mode sind die Flächen heller, weisser Text fällt unter 3:1. | „on-color“-Tokens: `--color-on-accent`, `-on-primary`, `-on-success`, `-on-danger`, `-on-warning`, `-on-member` | ✅ |
| T5 | 🟠 | Z-Indizes frei gewählt (1, 10, 20, 50, 100, 200, 1000, 9000, 9999, 10000), zwei Dialog-Overlays mit unterschiedlicher Abdunkelung (0.4 / 0.5). | Ebenen-Skala `--z-*`, `--color-scrim` | ✅ |
| T6 | 🟡 | Mitgliederfarben 3 und 4 als Hex in `utils/memberColor.ts`, ohne Dark-Variante. | `--member-3`, `--member-4` (Light/Dark) | ✅ |
| T7 | 🟡 | Kleinstwerte in px: `gap: 2px` (25×), Badge-Paddings `1px 6px` / `2px 8px` / `2px 10px` / `4px 12px`, Avatar- und Check-Kreis-Grössen. | `--space-0-5`, `--space-1-5`, `--badge-padding`, `--chip-padding`, `--avatar-*`, `--check-size` | ◐ Badges, Chips, Basis-Komponenten; Geometrie einzelner Spezialelemente (Kalender-Raster, Fortschrittsbalken) bleibt in px |
| T8 | 🟡 | Bewusste Ausnahmen: weisser Hintergrund hinter QR-Codes (Scanbarkeit), Kategorie- und Kalenderfarben in `utils/categoryColors.ts` / `stores/calendar.ts` (Nutzerdaten, keine UI-Tokens). | Kommentiert, nicht tokenisiert | ⏸ bewusst |
| T9 | 🟡 | Alt-Aliase `--color-primary-*`, `--color-text-*` parallel zur neuen Palette (`--ink`, `--sub`, …). | Beibehalten (stabile API für bestehende Views), in der Referenz als Alias markiert. Neue Styles nutzen die Palette bzw. semantische Tokens. | ⏸ |

## 2. Typografie

| # | Schwere | Befund | Fix | Status |
|---|---|---|---|---|
| Y1 | 🟠 | Karten- und Abschnittstitel uneinheitlich: `--text-base` (Dashboard, Essen, Tiere, Pflanzen, Ausgaben) gegen `--text-lg` (Haushalt, Putzplan, „Kein Haushalt“). Listentitel (16 px Nunito) und Kartentitel (16 px Quicksand) unterscheiden sich kaum. | Neue Stufe `--text-md` (18 px) als `--text-title-card`; alle Karten-/Abschnittstitel nutzen sie. Hierarchie: Seite 24 → Dialog 20 → Karte 18 → Eintrag 16 → Meta 14 → Badge 12. | ✅ |
| Y2 | 🟠 | Titel ohne Quicksand: eigene Dialogtitel in `ExpenseFormDialog`, `BalanceSummary`, Titel in `BaseEmptyState`, Pflanzen-/Tiernamen in Karten. | `font-family: var(--font-display)` ergänzt | ✅ |
| Y3 | 🟡 | px-Schriftgrössen: `8px`, `10px` (3×), `13px`, `16px` (2×), `0.75rem`. | `--text-2xs` (10 px) ergänzt; alle Grössen auf die Skala | ✅ |
| Y4 | 🟡 | `font-weight: 600` als Zahl (6×), `line-height: 1 / 1.3 / 1.5` als Zahl. | `--font-weight-*`, `--line-height-none/snug/normal` | ✅ |
| Y5 | 🟡 | Doppelte Auth-Styles (Login/Register identisch, bekannte Einschränkung). | Gemeinsame Datei `assets/auth.css`; beide Views importieren sie | ✅ |

## 3. Komponenten-Konsistenz

| # | Schwere | Befund | Fix | Status |
|---|---|---|---|---|
| K1 | 🔴 | **`BaseCard` ohne `#header`-Slot**: Titel „Was essen wir heute?“ in `FoodView.vue` wird nicht angezeigt (bekannte Einschränkung). Dasselbe Muster in `DashboardView`. | `BaseCard` rendert `#header` als `<header class="base-card__header">` mit Abstand zum Inhalt | ✅ |
| K2 | 🟠 | Zustände uneinheitlich: `BaseCheckCircle` ohne Fokus-Ring, ohne Hover; `BasePillTabs` ohne Fokus- und Press-Zustand; `BaseDialog`-Schliessen-Button ohne Fokus; `BaseInput` Fehler-Fokus zeigt Akzent- statt Fehler-Halo; Danger-Button ändert beim Hover die Farbe, alle anderen nur die Helligkeit. | Einheitlich: hover = Helligkeit/`--chip`, active = `scale(0.98)`, disabled = `opacity .5`, focus-visible = `--focus-outline`, loading = Spinner + `cursor: progress` | ✅ |
| K3 | 🟠 | Nachgebaute Pill-Tabs in `ShoppingView` (identisch zu `BasePillTabs`, aber `font-weight: 600` und eigener Add-Button). | Styles an `BasePillTabs` angeglichen (gleiche Tokens). Austausch durch die Komponente erfordert Template-Umbau (Add-Pill, Zähler) → offen | ◐ |
| K4 | 🟠 | Drei FABs mit unterschiedlicher Grösse (52 / 56 / 56 px), Farbe (`--card` / `#fff`) und Ebene. | `--fab-size`, `--color-on-accent`, `--z-fab` | ✅ |
| K5 | 🟡 | Eigene Dialog-Implementierungen in `ExpenseFormDialog` und `BalanceSummary` statt `BaseDialog` (andere Abdunkelung, Titel-Font, Transition). | Tokens angeglichen (Scrim, Titel, Radius). Ersatz durch `BaseDialog` = Template-Umbau → offen | ◐ |
| K6 | 🟡 | `BaseAvatar` mit px-Grössen 22/32 und px-Schrift 10/13. | `--avatar-sm/md`, `--text-2xs`/`--text-xs` | ✅ |
| K7 | 🟡 | `BaseSpinner` `aria-label="Lädt…"` fest auf Deutsch. | Nicht visuell → nur dokumentiert (i18n, `claude/ux-feedback`) | ⏸ |

## 4. Icons

| # | Schwere | Befund | Fix | Status |
|---|---|---|---|---|
| I1 | 🟠 | 13 verschiedene Grössen (12, 14, 16, 18, 20, 22, 24, 28, 32, 48, 56 …). 18 px (31×) liegt zwischen den Stufen. | Skala `--icon-size-xs/sm/md/lg/xl/display` = 12/16/20/24/32/48. 14 → 16, 18 → 20 (Icon-Buttons, Kartentitel) bzw. 16 (Top-Bar-Links), 22/28 → 24, 56 → 48 | ✅ |
| I2 | 🟠 | Emoji als Icon: `👤` vor Personen (Putzplan, Medikamenten-Log), `★` für Favoriten (Essen). Rendering abhängig vom System, nicht einfärbbar. | Phosphor `PhUser` / `PhStar weight="fill"` | ✅ |
| I3 | 🟡 | Gewichte: `light` (Medikamente leer) und `duotone` (einmalig) weichen ab. Regel: `regular` Standard, `fill` = aktiver Zustand, `bold` nur ≤ 16 px in Buttons und Bestätigungen. | `light` → `regular`; `duotone` in Hero-Icon bleibt (bewusst) | ✅ |
| I4 | 🟡 | Inline-`style="margin-right: 4px"` an Icons. | `var(--space-1)` | ✅ |
| I5 | 🟡 | Emoji für Ausgaben-Kategorien und Tierarten (`🛒 🏠 🐈 …`, `🐱 🐶 …`). | Bewusst belassen: Inhalt/Persönlichkeit, nicht Bedien-Icon. **Entscheidung Betreiber** | ⏸ |

## 5. Dark Mode

Vorhanden (`html[data-theme="dark"]`, Umschaltung über `useTheme`).

| # | Schwere | Befund | Fix | Status |
|---|---|---|---|---|
| D1 | 🔴 | Danger im Dark Mode unverändert `#DC2626` mit `--card`-Text (≈ 2.8 : 1): „Haushalt verlassen“, Fehler-Toasts, Überfällig-Badges kaum lesbar. | Dark-Danger `#E86E6E`, Hover `#F08A8A`, `--color-on-danger` = `--card` | ✅ |
| D2 | 🔴 | Helle Hardcodes (`#FFF5F5`, `#FECACA`, `#fff`-Text) – siehe T2/T4. | ✅ über Tokens | ✅ |
| D3 | 🟠 | Fehlende Dark-Werte für Mitgliederfarben 3/4, Overlay-Scrim, Danger-/Warning-Flächen. | Ergänzt | ✅ |
| D4 | 🟡 | Kein `color-scheme` gesetzt: native Controls (Select „Sprache“, Datumsfelder, Scrollbars) bleiben hell. | `color-scheme: light` / `dark` am Root | ✅ |

## 6. Farbkontraste (WCAG 2.1 AA)

Geprüft mit eigener Kontrastberechnung (relative Luminanz nach WCAG) für alle Text-auf-Fläche-Paare der Palette, Light und Dark. Schwellen: 4.5 : 1 für Text < 18.66 px fett / < 24 px, 3 : 1 für grosse Schrift, Icons und Badge-Flächen.

| Paar | Vorher | Nachher | Fix |
|---|---|---|---|
| Light `--acc` auf `--card` (Ghost-Buttons, Links) | 4.00 🔴 | 5.15 | `--acc` `#A0714A` → `#896140` |
| Light `--card` auf `--acc` (Primär-Button) | 4.00 🔴 | 5.15 | dito |
| Light `--acc` auf `--acc-soft` (aktiver Nav-Link, Badges) | 3.50 🔴 | 4.51 | dito |
| Light `--sub` auf `--bg` (Untertitel direkt auf Hintergrund) | 4.32 🟠 | 4.50 | `--sub` `#5F6D69` → `#5D6A66` |
| Light `--card` auf `--p1` (Info-Toast, Kategorie aktiv) | 4.23 🟠 | 4.52 | `--p1` `#3F827A` → `#3D7D75` |
| Light `--card` auf `--ok` (Erfolgs-Toast) | 3.29 🟠 | 4.50 | `--ok` `#6E9273` → `#5B795F` |
| Light `--p2` als Avatarfläche, weisse Initialen | 4.03 | 4.57 | `--p2` → `#936570`; `--member-3/4` abgedunkelt |
| Weiss auf `--color-warning` (Badges „heute fällig“, „läuft bald ab“) | 2.47 🔴 | 5.49 | Warn-Badges als Soft-Variante: `--color-warning-strong` auf `--color-warning-soft` |
| Dark `--color-danger` als Text / Fläche | 2.84 🔴 | 4.50 | siehe D1 |
| Dark `--sub` auf `--chip` | 4.42 | 4.53 | `--sub` `#93A29E` → `#96A4A0` |
| Dark weisse Initialen auf `--p1` (Avatar) | 2.80 | 5.83 | `--color-on-member` = `--bg` im Dark Mode |
| Offline-Banner Text auf `--color-warning` | undefiniert | 4.9 | `--color-on-warning` |

Die Tonwerte bleiben im selben Farbton (nur Helligkeit angepasst). **Sichtbarste Änderung: Akzent-Braun wird etwas dunkler.** → Entscheidung Betreiber, falls die alte Akzentfarbe Markenfarbe ist (dann `--acc` nur für Flächen, zusätzlicher `--acc-text`).

## 7. Bewegung

| # | Schwere | Befund | Fix | Status |
|---|---|---|---|---|
| M1 | 🟠 | Hardcodierte Dauern/Easings: `0.15s`, `0.2s`, `0.25s`, `0.3s`, `150ms`; Toast-Transitions in `App.vue` (bekannte Einschränkung), Dialog-, Sheet-, Check-Kreis-Transitions. | `--duration-fast/normal/slow`, `--ease-standard/out/in`, `--transition-*` | ✅ |
| M2 | 🟡 | `transition: all …` (11×) animiert auch Layout-Eigenschaften. | In Basis-Komponenten auf konkrete Eigenschaften reduziert; in Views belassen (kein sichtbarer Unterschied) | ◐ |
| M3 | 🟡 | `prefers-reduced-motion`: global vorhanden (`theme.css`), greift auch für Endlos-Animationen (Skeleton, Sync-Punkt, Spinner). Spinner dreht dann nicht mehr – Ladezustand bleibt über Farbe erkennbar. | Geprüft, keine Änderung nötig | ✅ |

## 8. Listen-Anatomie über Module

Soll-Anatomie: **[Icon/Avatar/Check] · Titel (16 px, semibold) · Sekundärzeile (14 px, `--sub`) · Badges (12 px) · Aktion rechts (Icon-Button 44 × 44)**.

| Modul | Container | Radius | Titel | Sekundärzeile | Aktion rechts | Abweichung |
|---|---|---|---|---|---|---|
| Einkauf | Zeile mit Trennlinie | – | 16 / 400 | 14 | Zuweisen, Menü | Gewicht 400 (bewusst leicht, abhakbar) |
| Aufgaben | Zeile mit Trennlinie | – | 16 / 400 | 14 | Icon-Buttons | wie Einkauf |
| Putzplan | Karte | 8 → 12 | 16 / 500 → 600 | 14 | Icon-Buttons | angeglichen |
| Pflanzen | grosse Karte mit Foto | 20 | 20 → 18 | 14 | Text-Link „Löschen“ 12 px | Titelgrösse angeglichen; Text-Link statt Icon dokumentiert |
| Haustiere | grosse Karte mit Foto/Emoji | 20 | 20 → 18 | 14 | Text-Link „Löschen“ 12 px | wie Pflanzen |
| Notizen | Karte | 6 → 12 | 16 / 600 | 14 / Datum 12 | – (ganze Karte klickbar) | Radius angeglichen |
| Tags | Karte | 6 → 12 | 16 / 600 | 14 | Chevron | Radius angeglichen |
| Dokumente | Karte | 6 → 12 | 16 / 600 | Datum 12 | Icon-Buttons | Radius angeglichen |

| # | Schwere | Befund | Fix | Status |
|---|---|---|---|---|
| L1 | 🟠 | Drei Radien für gleichartige Listen-Karten (6 / 8 / 20 px). | `--radius-item` (12 px) für Listen-Karten; grosse Foto-Karten behalten `--radius-card` | ✅ |
| L2 | 🟠 | Titelgewicht und -grösse variieren (400/500/600, 16/20 px). | `--text-title-item` (16 px / 600) für Karten-Einträge; abhakbare Zeilen (Einkauf, Aufgaben) bleiben 400 | ✅ |
| L3 | 🟡 | Pflanzen/Tiere: Löschen als roter Text-Link statt Icon-Button wie überall sonst. | Template-Änderung → offen, dokumentiert | ⏸ |
| L4 | 🟡 | Badge-Paddings in 7 Varianten. | `--badge-padding` / `--chip-padding` | ✅ |

---

## Offen / Entscheidungen für den Betreiber

1. **Akzentfarbe:** Für AA wurde `--acc` von `#A0714A` auf `#896140` abgedunkelt. Alternative: alte Farbe für Flächen behalten und `--acc-text` einführen (zwei Tokens, mehr Pflegeaufwand).
2. **Emoji für Kategorien und Tierarten** behalten (Persönlichkeit) oder durch Phosphor-Icons ersetzen (einheitlich, einfärbbar)?
3. **Dark Mode:** ist vorhanden und jetzt vollständig. Soll er Standard „System“ bleiben? Ein Test mit echten Fotos (Pflanzen/Tiere) im Dark Mode steht aus.
4. **Eigene Dialoge** (`ExpenseFormDialog`, `BalanceSummary`) auf `BaseDialog` umstellen – Template-Umbau, eigener Branch empfohlen.
5. **Pill-Tabs in `ShoppingView`** durch `BasePillTabs` ersetzen (braucht Slot für Zähler und Add-Pill).
6. **Löschen in Pflanzen-/Tierkarten** als Icon-Button wie in den anderen Modulen (Template-Änderung).
7. **Listen-Zeile vs. Listen-Karte:** Einkauf/Aufgaben nutzen Zeilen mit Trennlinie, alle anderen Karten. Beides ist vertretbar (Zeilen = schnelles Abhaken). Vereinheitlichung wäre eine Gestaltungsentscheidung, keine Fehlerbehebung.
