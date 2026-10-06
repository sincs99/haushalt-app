# Mobile-Layout-Review

Stand: 2026-10-06 · Branch `claude/mobile-layout-fixes`

Systematische Prüfung aller Routen im echten Browser (Chromium/Playwright) mit
Screenshots und automatischer Layout-Prüfung, anschliessend Behebung der
Befunde (ein Commit pro Befund, Screenshot-Verweise in den Commit-Messages).

## Vorgehen

**Umgebung.** Backend mit SQLite (`DATABASE_URL=sqlite:////tmp/casa.db`),
Frontend über `npm run dev` (Vite-Proxy auf :8000). Abweichungen nur in der
lokalen Testumgebung, nichts davon ist eingecheckt:

- `alembic upgrade head` läuft auf SQLite nicht durch (ALTER von Constraints);
  das Schema wurde wie in den Backend-Tests per `Base.metadata.create_all` angelegt.
- `RATELIMIT_ENABLED=false`, sonst blockieren Registrierung (3/h) und Login
  (5/min) das Anlegen der Testdaten und die vielen Seitenaufrufe.
- SQLite liefert Datetimes ohne Zeitzone; `GET /dashboard` scheitert daran mit
  HTTP 500 (`can't compare offset-naive and offset-aware datetimes`). Mit
  PostgreSQL (`timestamptz`) tritt das nicht auf. Für den Test wurden geladene
  Datetimes per SQLAlchemy-Event als UTC markiert.

**Testdaten** (`frontend/qa/seed-testdata.py`): Haushalt mit zwei Mitgliedern
(Einladungscode), ein Nutzer ohne Haushalt, lange Namen mit Umlauten
(„Anna-Lena Müller-Lüdenscheidt“, „Prinzessin Mausi von Schnurrhausen“,
„Monstera deliciosa „Thai Constellation“ im Wohnzimmer“), 30 Einkaufsartikel
in 5 Geschäften plus zweite/dritte Liste, Ausgaben bis CHF 245'000, Budget
überschritten, Ausgleichszahlung, Ämtli-Rotation, Termin über Mitternacht,
Abstimmung, Rezept mit 30 Zutaten und 11 Schritten, Wochenplan, Notizen,
Dokumente mit Ablaufdatum, Tags. Kein KI-Schlüssel → KI-Karten ausgeblendet,
`/assistant` zeigt „nicht eingerichtet“ (geprüft).

**Audit-Skript** (`frontend/qa/mobile-audit.cjs`):

| Viewport | Insets | Zweck |
|---|---|---|
| 360×780 | keine | kleines Android |
| 390×844 | unten 34 px (CDP `Emulation.setSafeAreaInsetsOverride`) | iPhone |
| 430×932 | unten 34 px | grosses iPhone |
| 390×500 | keine | Bildschirmtastatur offen (alle Dialoge/Formulare, Mehr-Menü) |

Jeweils Light und Dark (`casa_theme`), DE und EN (`haushalt_locale`). Pro Route:
Grundzustand, ans Ende gescrollt, alle Pill-Tabs, alle „Hinzufügen/Bearbeiten/
Verwalten“-Dialoge sowie routenspezifische Zustände (Artikel-Sheet,
Geschäft-Menü, Kalender Tag/Monat/Termin bearbeiten, Rezeptdetail,
Ausgleich, Tag-Detail mit QR, Haushalt verlassen …) und das Mehr-Menü.

Geprüft wird pro Zustand: horizontaler Scroll und Elemente ausserhalb des
Viewports, Text, der sein Element überragt, überlappende Flex/Grid-Geschwister,
Tap-Ziele < 44×44 px (inkl. Vergrösserung per `::after` und Abschneiden durch
Scroll-Container), sich überlappende Tap-Flächen, Inhalt unter Bottom-Nav,
fixe Elemente (FAB), die Inhalte verdecken, Bedienelemente im Safe-Area-
Bereich, abgeschnittener Inhalt bei fester Höhe, Dialoge/Sheets höher als der
Viewport ohne Scroll.

Ausführen:

```bash
cd frontend
python qa/seed-testdata.py qa/mobile/seed.json      # leere DB, Rate-Limit aus
NODE_PATH=$(npm root -g) node qa/mobile-audit.cjs --out=qa/mobile/run
# schneller: --quick (nur Light), --only=/route
```

Screenshots und `summary.tsv`/`findings.json` landen unter
`frontend/qa/mobile/` (in `.gitignore`). Die in den Commits genannten Dateien
(`qa/mobile/before/…`, `qa/mobile/after-NN-…/…`) stammen aus diesen Läufen.

## Befunde

| # | Route | Viewport | Beschreibung | Ursache | Fix |
|---|---|---|---|---|---|
| 1 | `/expenses` | alle, v. a. 360×780 | Seite 531 px breit, horizontaler Scroll; Bottom-Nav und Dialoge wurden mitverbreitert (Ausgabe-Dialog rechts abgeschnitten) | Ausgleichszahlung-Zeile: Namen, Betrag, Datum/Notiz und Löschen in einer Flex-Zeile ohne `min-width: 0`/`flex-wrap` | `2410f67` |
| 2 | `/shopping`, `/todos`, `/chores`, `/expenses`, `/household`, `/dashboard` | 390×844, 430×932 | Letzter Eintrag liegt ans Ende gescrollt halb unter der Bottom-Nav | Nav wächst um `env(safe-area-inset-bottom)`, `.app-content` reserviert nur 64 px | `cfebb74` (Tokens `--safe-bottom`, `--bottom-nav-space`) |
| 3 | `/calendar` | 390×844, 430×932 | „Neuer Termin“-FAB 13 px über der Bottom-Nav | `bottom: 80px` ohne Safe-Area | `64caccc` (`--fab-bottom`) |
| 4 | `/pets`, `/plants` | alle | FAB verdeckt am Seitenende den Löschen-Button der letzten Karte | kein Platz unter der letzten Karte | `64caccc` |
| 5 | `/todos` | alle | „Überfällig“-Badge quetscht lange Titel auf ~12 Zeichen pro Zeile | Titelzeile ohne `flex-wrap` | `789ee2c` |
| 6 | `/food`, `/assistant` | alle | Inhalt 32 px schmaler als auf anderen Seiten, Rezeptnamen früh abgeschnitten, Titel nicht bündig | View setzt zusätzlich zu `.app-content` eigenes Padding | `9c47d92` |
| 7 | Mehr-Menü | 360×560 / 390×500 | Sheet oben abgeschnitten (Oberkante −26 px), Titel und erster Eintrag unerreichbar | kein `max-height`/Scroll | `c4e5fd2` |
| 8 | `/expenses` → „Als bezahlt markieren“ | alle, 390×500 | Dialog ohne Innenabstand; mit Abstand bei offener Tastatur höher als der Viewport | Token `--space-5` existiert nicht; kein `max-height` | `3ea6a17` |
| 9 | `/household` | alle | „Admin“-Badge ohne Innenabstand | Token `--space-0-5` existiert nicht | `b8dfcca` |
| 10 | alle | alle | Abhak-Kreis 22 px, Dialog-Schliessen 26 px, Pill-Tabs 31 px, kleine Buttons 36 px | Basis-Komponenten unter 44 px | `089896f` (Utility `.tap-target`, Token `--tap-min`) |
| 11 | `/shopping` | 360×780, 390×844 | „+“ für neue Liste bei langem Listennamen ausserhalb der Pill-Leiste | Button am Ende eines horizontalen Scroll-Containers | `f6cd713` (sticky) |
| 12 | `/shopping`, `/notes`, `/pets`, `/plants`, Detailseiten, `/calendar`, `/food`, `/expenses`, `/household`, `/tags`, `/register`, `/t/…` | alle | Icon-Buttons, Löschen-Links, Chips, Wochen-Pfeile 22–38 px | Einzelkomponenten unter 44 px | `afbed1f` |
| 13 | `/todos`, `/chores`, `/documents`, Katze/Pflanze Detail, `/food` | alle | Vergrösserte Tap-Flächen benachbarter Buttons überlappen 2–6 px (Tipp auf den Rand löst Nachbaraktion aus) | Abstand 4 px zwischen Icon-Buttons | `8e11fb3` |
| 14 | Formulare in allen Dialogen, `/household`, `/chores`, `/todos`, `/calendar` | alle | Eingabefelder/Selects 34–42 px, Checkbox-Zeilen 21–24 px, Aufgaben/Ämtli-Umschalter 37 px, Farbwähler 32 px, Kalender-Filterchips vom Scroll-Container abgeschnitten | keine Mindesthöhe | `f2590e0` |
| 15 | `/documents`, `/expenses` (Rechnung buchen), KI-Rezeptkarte | alle | Selects 40–42 px, KI-Chips 36 px | komponenteneigene `min-height` unter 44 px überschreibt die globale | `0026e1d` |
| 16 | `/calendar` (Woche, Monat) | 360×780 | Tage 39–41 px breit | 7 Spalten in 328 px; Zellen liegen lückenlos nebeneinander | offen, akzeptiert: 44 px Breite geht nur mit anderem Raster (Design-Entscheidung) |
| 17 | Katze → Bearbeiten → Gesundheit | alle | Schweregrad-Punkte 18×18 px, 4 px untereinander | Layout | offen: vergrösserte Flächen würden sich überlappen; braucht anderes Layout (z. B. Segment-Control) → `claude/ui-design-audit` |
| 18 | `/chores` | alle | Ämtli-Checkbox 17×20 px | — | kein Fix nötig: die ganze Zeile (`.assignment-row__main`) ist klickbar; das Skript kennt Klick-Handler nicht |
| 19 | `/calendar` | alle | Avatare in Terminkarten überlappen 4 px | — | kein Befund: gewollter Avatar-Stapel (negativer Margin) |

**Summe:** 19 gemeldete Punkte, davon 15 behoben, 2 offen (16, 17) und 2 ohne
Handlungsbedarf (18, 19). Sprache: EN wurde in allen Zuständen bei 360 px
geprüft; kein eigener EN-Befund (keine Texte, die nur auf Englisch
überlaufen).

Schlusslauf (`qa/mobile/final/summary.tsv`, alle Viewports, Light/Dark,
DE/EN): nur noch die Punkte 16–19.

## Für andere Branches notiert (nicht behoben)

### `claude/ui-design-audit`

- **Nicht definierte Tokens**: `--color-neutral-50…900`, `--surface`,
  `--border`, `--shadow-sm`, `--green`, `--warn`, `--ink-secondary` (u. a.
  `App.vue`, `ChoresView`, `HouseholdView`, `PetDetailView`,
  `ExpenseFormDialog`, `BalanceSummary`, `ShoppingView`). Folge: Eingabefelder
  im Ausgleichs-Dialog und im Neue-Liste-Dialog haben keinen sichtbaren Rand.
- Hartkodierte Farbe `#FFF5F5` für überfällige Aufgaben (`TodoList.vue`),
  im Dark Mode nicht angepasst.
- Kalender: Pill-Tabs und Kalender-Chips sind gegenüber dem Seitentitel um
  16 px eingerückt, Monatsraster ebenso (andere Seiten bündig).
- Schweregrad-Auswahl im Gesundheitseditor (siehe Befund 17).
- Schreibweise uneinheitlich: „Gießen“, „Alle fälligen gießen“ (ß) neben
  Schweizer Schreibweise sonst („Schliessen“, „Gleichmässig“).

### `claude/ux-feedback`

- Termin über Mitternacht: am zweiten Tag zeigt die Karte „Tag 2/2 · 20:00“
  (Startzeit) statt der Endzeit 02:30.
- Kalender, Tag gewählt (nicht heute): Leerzustand sagt „Keine Termine heute“.
- Nutzer ohne Haushalt (`/no-household`) sieht die volle Bottom-Nav, obwohl
  alle Ziele einen Haushalt voraussetzen.
