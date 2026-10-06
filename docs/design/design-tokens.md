# Design-Tokens

Quelle: [`frontend/src/assets/theme.css`](../../frontend/src/assets/theme.css). Befunde und Begründungen: [`ui-audit.md`](ui-audit.md).

**Regeln**

- In Komponenten und Views stehen keine Hex-, `rgb()`- oder `rgba()`-Werte. Farben kommen aus der Palette (`--ink`, `--card`, …) oder aus semantischen Tokens (`--color-danger`, `--color-on-accent`, …).
- Schrift, Abstand, Radius, Schatten, Ebene und Dauer immer über Tokens. px nur für Geometrie von Spezialelementen (Kalender-Raster, Fortschrittsbalken, 1-px-Rahmen).
- Text auf farbiger Fläche nutzt das passende `--color-on-*`-Token, nie `#fff`.
- Neue Werte werden als Token ergänzt, nicht als Sonderfall in einer Komponente.
- Dark Mode (`html[data-theme="dark"]`) überschreibt nur Palette und Werte, die sich nicht aus ihr ableiten. Jeder neue Farb-Token braucht eine Prüfung in beiden Themes.

## Farben: Palette

| Token | Light | Dark | Bedeutung | Beispiel |
|---|---|---|---|---|
| `--bg` | `#DDE8E4` | `#182220` | App-Hintergrund | `body` |
| `--card` | `#FBF8F3` | `#22302D` | Karten, Sheets, Dialoge, Inputs | `BaseCard` |
| `--ink` | `#3A423F` | `#E8EFEC` | Primärtext, aktive Pill | Titel |
| `--sub` | `#5D6A66` | `#96A4A0` | Sekundärtext, Icons in Ruhe | Meta-Zeilen |
| `--line` | `rgba(58,66,63,.10)` | `rgba(255,255,255,.10)` | Trennlinien | Listen-Zeilen |
| `--line-strong` | `rgba(58,66,63,.22)` | `rgba(255,255,255,.26)` | Rahmen von Eingaben/Checkboxen | `BaseInput` |
| `--chip` | `#EAF1EE` | `#2C3B38` | Chips, sekundäre Buttons, Hover | `BaseButton secondary` |
| `--acc` | `#896140` | `#C79A6E` | Akzent: Primär-Button, aktiver Zustand, Links | `BaseButton primary` |
| `--acc-soft` | `#F2E8DC` | `#3A2F23` | Akzent-Fläche, Fokus-Halo | Ghost-Hover |
| `--nav` | `#E8F0EC` | `#1E2A28` | Bottom-Navigation | `TheBottomNav` |
| `--p1` | `#3D7D75` | `#5FA79E` | Teal: Info, Mitglied 1 | Info-Toast |
| `--p2` | `#936570` | `#C1919B` | Rosa: Mitglied 2 | Avatar |
| `--ok` | `#5B795F` | `#8AB08F` | Erfolg, erledigt | `BaseCheckCircle` |
| `--member-3` | `#7F6577` | `#B49AAC` | Mitglied 3 (Mauve) | Avatar |
| `--member-4` | `#77705F` | `#ABA390` | Mitglied 4 (Olive) | Avatar |

## Farben: Semantisch

| Token | Light | Dark | Bedeutung | Beispiel |
|---|---|---|---|---|
| `--color-success` | `--ok` | `--ok` | Erfolg | Erfolgs-Toast |
| `--color-danger` | `#DC2626` | `#E86E6E` | Destruktiv, Fehler, überfällig (Fläche und Text) | `BaseButton danger` |
| `--color-danger-hover` | `#B91C1C` | `#F08A8A` | Hover Danger-Button | |
| `--color-danger-soft` | `#FDECEC` | `#3A2424` | Fehlerfläche, Hover destruktiver Icon-Buttons | Auth-Fehler, überfälliges Todo |
| `--color-danger-strong` | `#B91C1C` | `#F0A3A3` | Text auf `--color-danger-soft` | |
| `--color-danger-border` | `#FECACA` | `#6B3434` | Rahmen von Fehlerflächen | Auth-Fehler |
| `--color-danger-light` | → `--color-danger-soft` | | Alt-Alias | |
| `--color-warning` | `#C09A62` | `#C09A62` | Warnung – **nur Fläche/Punkt**, nie Text auf `--card` | Sync-Punkt, Offline-Banner |
| `--color-warning-soft` | `#F7EEDF` | `#3A3020` | Warn-Badge-Fläche | „heute fällig“ |
| `--color-warning-strong` | `#7A5A2A` | `#E5C79A` | Warn-Text | „heute fällig“ |
| `--color-on-accent` | `--card` | `--card` | Vordergrund auf `--acc` | Primär-Button, FAB |
| `--color-on-primary` | `--card` | `--card` | Vordergrund auf `--p1` | Kamera-Button |
| `--color-on-success` | `--card` | `--card` | Vordergrund auf `--ok` | Häkchen |
| `--color-on-danger` | `#FFFFFF` | `--card` | Vordergrund auf `--color-danger` | Überfällig-Badge |
| `--color-on-warning` | `#26302D` | `#26302D` | Vordergrund auf `--color-warning` | Offline-Banner |
| `--color-on-member` | `#FFFFFF` | `--bg` | Initialen auf Mitgliederfarbe | `BaseAvatar` |
| `--color-scrim` | `rgba(0,0,0,.4)` | `rgba(0,0,0,.6)` | Abdunkelung hinter Overlays | `BaseDialog` |
| `--color-fallback` | `#8B8B8B` | | Neutrale Ersatzfarbe für Nutzerfarben | Kalender ohne Farbe |
| `--color-surface-subtle` | `--chip` | | Leicht abgesetzte Fläche | Tabellenkopf Putzplan |
| `--color-border` / `--color-border-strong` | `--line` / `--line-strong` | | Aliase | |

Alt-Aliase (bestehende Views, nicht für neuen Code): `--color-primary(-hover/-dark/-light)`, `--color-bg`, `--color-surface`, `--color-text`, `--color-text-secondary`, `--color-text-muted`.

## Typografie

Quicksand (`--font-display`) nur für Seiten-, Dialog-, Karten- und Abschnittstitel. Alles andere Nunito (`--font-family`).

| Token | Wert | Rolle | Beispiel |
|---|---|---|---|
| `--text-2xs` | 0.625rem / 10 px | Mini-Zähler, Avatar sm | `BaseAvatar sm` |
| `--text-xs` | 0.75rem / 12 px | Badges, Datum | `.due-badge` |
| `--text-sm` | 0.875rem / 14 px | Sekundärzeile, Labels, Buttons sm | `.item-row__meta` |
| `--text-base` | 1rem / 16 px | Body, Listentitel, Inputs (verhindert iOS-Zoom) | `BaseInput` |
| `--text-md` | 1.125rem / 18 px | Karten- und Abschnittstitel | `.card-title` |
| `--text-lg` | 1.25rem / 20 px | Dialog-/Sheet-Titel, leere Zustände | `BaseDialog` |
| `--text-xl` | 1.5rem / 24 px | Seitentitel | `PageHeader` |
| `--text-2xl` | 2rem / 32 px | Kennzahlen, Hero-Emoji | Tierkarte |

| Rollen-Token | → | Verwendung |
|---|---|---|
| `--text-title-page` | `--text-xl` | `PageHeader`, Auth-Titel |
| `--text-title-dialog` | `--text-lg` | `BaseDialog`, eigene Dialoge, `BaseEmptyState` |
| `--text-title-card` | `--text-md` | Karten-/Abschnittstitel (Quicksand 600) |
| `--text-title-item` | `--text-base` | Einträge in Listen-Karten (Nunito 600) |
| `--text-secondary` | `--text-sm` | Sekundärzeile |
| `--text-badge` | `--text-xs` | Badges |

| Token | Wert | | Token | Wert |
|---|---|---|---|---|
| `--line-height-none` | 1 | | `--font-weight-normal` | 400 |
| `--line-height-tight` | 1.25 | | `--font-weight-medium` | 500 |
| `--line-height-snug` | 1.35 | | `--font-weight-semibold` | 600 |
| `--line-height-normal` | 1.5 | | `--font-weight-bold` | 700 |

## Abstände

4-px-Raster; `0-5` und `1-5` nur für Feinheiten (Badge-Innenabstand, Abstand Titel/Meta).

| Token | Wert | Beispiel |
|---|---|---|
| `--space-0-5` | 2 px | Abstand Titel ↔ Sekundärzeile, Badge vertikal |
| `--space-1` | 4 px | Icon ↔ Text in Badges |
| `--space-1-5` | 6 px | Pill-Tabs vertikal |
| `--space-2` | 8 px | Gap in Zeilen, Badge horizontal |
| `--space-3` | 12 px | Padding Listen-Karte, Input |
| `--space-4` | 16 px | Padding Karte, Seitenrand |
| `--space-5` | 20 px | Popover-Padding |
| `--space-6` | 24 px | Padding Dialog |
| `--space-8` | 32 px | Leere Zustände |
| `--space-10` / `--space-12` | 40 / 48 px | grosse Abstände |

| Komponenten-Token | Wert | Beispiel |
|---|---|---|
| `--badge-padding` | 2 px 8 px | Status-Badges, Zähler |
| `--chip-padding` | 6 px 16 px | `BasePillTabs`, Geschäfts-Chips |
| `--chip-padding-sm` | 4 px 12 px | Kategorie-/Filter-Chips |

## Radien

| Token | Wert | Beispiel |
|---|---|---|
| `--radius-xs` | 4 px | Balken, Rasterzellen |
| `--radius-sm` | 6 px | Icon-Buttons, kleine Flächen |
| `--radius-md` | 8 px | Toasts |
| `--radius-lg` | 12 px | Modals (klein) |
| `--radius-btn` | 12 px | Buttons, Inputs |
| `--radius-item` | 12 px | Listen-Karten (Notizen, Tags, Dokumente, Ämtli) |
| `--radius-xl` | 16 px | Bottom-Sheet oben |
| `--radius-card` | 20 px | `BaseCard`, Foto-Karten |
| `--radius-dialog` | 24 px | Dialoge |
| `--radius-full` | 999 px | Pills, Badges, Avatare, FAB |

## Schatten und Fokus

| Token | Light | Dark | Beispiel |
|---|---|---|---|
| `--shadow-card` | `0 1px 3px rgba(0,0,0,.08), 0 1px 2px rgba(0,0,0,.06)` | stärker (.25/.20) | Karten |
| `--shadow-sm` | → `--shadow-card` | | Alias |
| `--shadow-overlay` | `0 4px 12px rgba(0,0,0,.15)` | `.40` | Dialoge, FAB, Toasts |
| `--focus-ring` | `0 0 0 3px var(--acc-soft)` | | Inputs (Halo) |
| `--focus-outline` | `2px solid var(--acc)` | | Buttons, Links, Checkboxen (`:focus-visible`) |

## Bewegung

| Token | Wert | Verwendung |
|---|---|---|
| `--duration-fast` | 150 ms | Hover, Farbwechsel, Press |
| `--duration-normal` | 200 ms | Ein-/Ausblenden, Dialoge |
| `--duration-slow` | 300 ms | Sheets, Toast-Eintritt |
| `--ease-standard` | `ease` | Zustandswechsel |
| `--ease-out` | `cubic-bezier(.2,0,0,1)` | Eintritt |
| `--ease-in` | `cubic-bezier(.4,0,1,1)` | Austritt |
| `--transition-fast` / `-normal` / `-slow` | Dauer + Easing | `transition: color var(--transition-fast)` |
| `--toast-duration` | 4000 ms | Anzeigedauer Toast |

`prefers-reduced-motion: reduce` setzt global alle Animationen und Transitions auf 0.01 ms (`theme.css`).

## Icons

Phosphor (`@phosphor-icons/vue`). Die `:size`-Props folgen derselben Skala; die CSS-Tokens gelten für Container und Nicht-Phosphor-Grafiken.

| Token | Wert | Kontext |
|---|---|---|
| `--icon-size-xs` | 12 px | in Badges, Check-Kreis |
| `--icon-size-sm` | 16 px | Buttons sm, Meta-Zeilen, Top-Bar-Links, Chip-Entfernen |
| `--icon-size-md` | 20 px | Buttons md, Icon-Buttons, Kartentitel, Listen-Icons |
| `--icon-size-lg` | 24 px | Bottom-Navigation, FAB, Zurück-Pfeil, Tag-Icon |
| `--icon-size-xl` | 32 px | Karten-Hero |
| `--icon-size-display` | 48 px | Leere Zustände, Erfolg nach Tag-Scan |

Gewicht: `regular` Standard · `fill` aktiver Zustand (Navigation, Favorit, angeheftet) · `bold` nur bei ≤ 16 px in Buttons und Bestätigungs-Häkchen.

## Grössen

| Token | Wert | Beispiel |
|---|---|---|
| `--touch-target` | 44 px | Mindestgrösse Buttons/Icon-Buttons |
| `--avatar-sm` / `-md` / `-lg` | 22 / 32 / 48 px | `BaseAvatar` |
| `--check-size` | 22 px | `BaseCheckCircle` |
| `--fab-size` | 56 px | FAB in Pflanzen, Tiere, Kalender |
| `--bottom-nav-height` | 64 px | Abstand Inhalt/Toast über der Navigation |

## Ebenen (z-index)

| Token | Wert | Beispiel |
|---|---|---|
| `--z-raised` | 1 | Element über Geschwistern |
| `--z-sticky` | 10 | Sticky-Elemente in Listen |
| `--z-dropdown` | 20 | Menüs in Listen |
| `--z-fab` | 50 | FAB |
| `--z-nav` | 100 | Bottom-Nav, Top-Bar |
| `--z-sheet` | 200 | Bottom-Sheets |
| `--z-dialog` | 1000 | Dialoge |
| `--z-popover` | 9000 | Popover über Dialogen |
| `--z-banner` | 9999 | Offline-Banner |
| `--z-toast` | 10000 | Toasts |
