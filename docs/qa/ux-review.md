# UX-Review (Stand 2026-10-06)

**Nachtrag vom 7. Oktober 2026:** Q-18 ist im aktuellen Reparaturstand behoben: `npm run typecheck` prüft `tsconfig.app.json`, der Build führt dieselbe Prüfung aus, und die Vue-Augmentation ist ein eigenes TypeScript-Modul. App-Typprüfung und Produktionsbuild bestehen. Die Tabellen unten dokumentieren den ursprünglichen Review-Stand; weitere Korrekturen und aktuelle lokale Prüfnachweise stehen in [current-audit-fixes.md](current-audit-fixes.md). Produktion und ein echtes iPhone sind damit nicht verifiziert.

Review aus Sicht UX-Design über alle Module, durchgeführt am Code (Vue-Views, Stores, Locales) entlang der acht Prüfpunkte: Feedback nach Aktionen, Lade-/Leer-/Fehlerzustände, Offline, destruktive Aktionen, Formulare, Navigation, UX-Copy, Erreichbarkeit (grob).

**Schwere**
- **hoch** – Nutzer wird getäuscht oder verliert Daten, Kernaktion ohne Rückmeldung, Erfolg als Fehler angezeigt
- **mittel** – fehlender Lade-/Fehlerzustand oder „Erneut versuchen“, fehlendes Undo, fehlender Doppelklick-Schutz, fehlendes Feedback bei Nebenaktionen, fehlende Fehlercode-Übersetzung
- **gering** – Copy, Feinschliff, kleinere A11y-Punkte

**Status**: ✅ behoben · ◐ teilweise · ⏳ offen (Begründung im Abschnitt „Offen und warum“)

**Übersicht** (146 Befunde)

| Schwere | Anzahl | ✅ behoben | ◐ teilweise | ⏳ offen |
|---|---|---|---|---|
| hoch | 34 | 32 | 1 (P-1: Rückmeldung ja, Undo fehlt) | 1 (M-2) |
| mittel | 85 | 75 | 5 | 5 |
| gering | 27 | 24 | 3 | 0 |

Nicht in diesem Branch (nur notiert): reine Layout-Fehler (→ `claude/mobile-layout-fixes`) und Design-System-Konsistenz (→ `claude/ui-design-audit`), siehe Abschnitt „Ausserhalb des Scopes“.

---

## Einheitliches Feedback-Muster

Statt je View eigene Toasts zu basteln, gibt es jetzt drei Bausteine:

| Baustein | Zweck |
|---|---|
| `useToast()` → `notifySuccess`, `notifyInfo`, `notifyError(fallback, err)`, `notifyUndoable(text, undo)` | Erfolgs-/Hinweis-/Fehlermeldung. `notifyError` übersetzt API-Fehlercodes (`errors.<CODE>`), Netzwerk- und Offline-Fehler, sonst gilt der Fallback-Text. `notifyUndoable` zeigt 6 s lang „Rückgängig“; Undo läuft genau einmal, Fehler beim Undo werden gemeldet. Gleiche Meldungen werden nicht gestapelt, höchstens drei Toasts. Fehler-Toasts sind `role="alert"`. |
| `useAsyncAction()` → `run(fn, { key, success, undo, error, requireOnline })`, `isPending(key)` | Für jede Aktion, die einen Request auslöst: Doppelklick-Schutz pro Schlüssel (z. B. Pflanzen-ID), ohne Netz Hinweis „Du bist offline – die Änderung wurde nicht gespeichert.“ statt fehlschlagendem Request, Erfolgs-Toast (optional mit Undo), übersetzte Fehlermeldung. |
| `useLoader(load)` + `BaseErrorState` | Fehlerzustand für Listen mit „Erneut versuchen“, statt nach einem Ladefehler fälschlich den Leerzustand („Noch keine …“) zu zeigen. |
| `useBackClose(open, close)` (in `BaseDialog` und `MoreSheet` eingebaut) | Zurück-Taste (Android/Browser) schliesst Dialog/Sheet statt die Seite zu verlassen. |

Regel für Erfolgs-Toasts: **nur** wenn das Ergebnis nicht direkt sichtbar ist (Gegossen, Gefüttert, Alle giessen, Ämtli/Aufgabe erledigt, Rechnung gebucht, Auf Einkaufsliste gesetzt, Termin ausserhalb der sichtbaren Woche, Abstimmung entschieden). Sichtbare Listenänderungen (Abhaken in der Liste, neue Zeile) brauchen keinen Toast; Undo dort, wo Löschen/Abhaken leicht versehentlich passiert.

---

## Querschnitt

| ID | Modul | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|---|
| Q-1 | Alle | hoch | Ladefehler werden verschluckt; Views zeigen danach den Leerzustand („Noch keine Pflanzen/Katzen/Tags/Dokumente“, „Erste Liste erstellen“). Wirkt wie Datenverlust und verleitet zum Doppelt-Anlegen. | `useLoader` + `BaseErrorState` mit „Erneut versuchen“; Leerzustand nur ohne Fehler. | ✅ |
| Q-2 | Alle | hoch | Offline lösen alle Aktionen Requests aus; optimistische Änderung springt zurück, generischer Fehler oder rohes „Network Error“. Eingetippter Text (Quick-Add Einkauf/Aufgaben/Notizen) geht verloren. | `useAsyncAction` mit `requireOnline` (Hinweis statt Request), Eingabe erst nach Erfolg leeren. | ✅ |
| Q-3 | Alle | mittel | Fehler-Toasts übergeben den Fehler nicht; Fehlercodes vom Backend werden nie angezeigt. | `notifyError(fallback, err)`. | ✅ |
| Q-4 | Alle | mittel | 36 Backend-Fehlercodes ohne `errors.*`-Übersetzung (u. a. `FEEDING_DUPLICATE`, `POLL_ALREADY_DECIDED`, `MEAL_PLAN_DATE_TAKEN`, `LAST_CALENDAR`, `EVENT_END_BEFORE_START`, `NOTE_NOT_FOUND`, `REFRESH_TOKEN_EXPIRED`); Pydantic-422 und HTTP-5xx erscheinen roh auf Englisch. | Keys in DE/EN ergänzen, 422 → `errors.validation`, 5xx → `errors.server`, nie `error.message` anzeigen. | ✅ |
| Q-5 | Alle | mittel | `BaseDialog`: keine Zurück-Taste, keine Fokusfalle, Fokus geht nicht zum Auslöser zurück, Escape nur mit Fokus im Dialog, `autofocus` im Inhalt wirkungslos (Panel bekommt Fokus). | `useBackClose`, Fokusfalle, Fokus aufs erste Feld, Fokus zurück, `aria-labelledby`. | ✅ |
| Q-6 | Alle | mittel | Speichern-Buttons liegen im Dialog-Footer ausserhalb des `<form>` – Enter sendet bei Formularen mit mehreren Feldern nicht. | `<form id>` + `type="submit" form="id"`. | ✅ |
| Q-7 | Alle | mittel | Lösch-Bestätigungen ohne `:loading`; Doppeltipp löscht zweimal → Erfolgs- und 404-Fehler-Toast. | Pending-Guard. | ✅ |
| Q-8 | Alle | mittel | Datumswerte per `toISOString()` (UTC): zwischen 00:00 und 02:00 Schweizer Zeit ist „heute“ gestern (Ausgaben-/Ausgleichsdatum, „Heute gegeben“, Fälligkeiten Haustiere). | Lokales Datum (`localDateString`). | ✅ |
| Q-9 | Shell | hoch | Desktop (≥ 768 px): Bottom-Nav und „Mehr“ ausgeblendet, Top-Bar hat keinen Eintrag – Haustiere, Pflanzen, Essen, Notizen, Ablage, KI nicht erreichbar. | „Mehr“-Button in der Top-Bar öffnet das Sheet. | ✅ |
| Q-10 | Shell | mittel | „Mehr“-Tab nur auf 4 Routen aktiv, auf Haustiere/Pflanzen/Essen/Notizen/Detailseiten gar kein Tab aktiv. | Aktiv für alle Routen ohne eigenen Tab. | ✅ |
| Q-11 | Shell | mittel | `MoreSheet`: Zurück-Taste verlässt die Seite, Einträge nicht per Tastatur erreichbar. | `useBackClose`, `role="link"`, Enter/Space. | ✅ |
| Q-12 | Shell | mittel | Router ohne `scrollBehavior`: Scroll-Position wird zwischen Seiten mitgenommen und bei Zurück nicht wiederhergestellt. | `savedPosition ?? { top: 0 }`. | ✅ |
| Q-13 | Shell | mittel | Fehler-Toasts `role="status"`, verschwinden nach 4 s. | Fehler als `role="alert"`. | ✅ |
| Q-14 | Shell | gering | Kein 404-Fallback; eingeloggte Nutzer sehen auf `/login` das Login-Formular in der App-Shell. | Catch-all-Route, Gast-Guard. | ✅ |
| Q-15 | Shell | gering | `aria-label="Navigation"` hartkodiert; Haushalts-Select ohne Label. | i18n-Key, `aria-label`. | ✅ |
| Q-16 | Shell | gering | `BaseInput`-ID aus dem Label abgeleitet → doppelte IDs bei gleichem Label; Fehlertext nicht per `aria-describedby` verknüpft. | Eindeutige ID, `aria-invalid`/`aria-describedby`. | ✅ |
| Q-17 | Alle | gering | Klickbare Karten/Zeilen als `<div @click>` (Dashboard, Pflanzen, Haustiere, Notizen, Ausgaben, Kalender) – per Tastatur nicht erreichbar. | `role="button" tabindex="0"` + Enter, oder `<router-link>`. | ✅ |
| Q-18 | Werkzeug | mittel | `npm run typecheck` prüft nichts: `tsconfig.json` hat `"files": []` mit Referenz, `vue-tsc --noEmit` ohne `-b`. Darum fiel der Kalender-Fehler K-1 nicht auf. Mit `-p tsconfig.app.json` gibt es ~170 Fehler „Module 'vue' has no exported member …“ (Versions-Mismatch vue-tsc 2 / Vue 3.5). | Eigenes Vorhaben: vue-tsc aktualisieren, `-b` verwenden, Altfehler beheben. | ⏳ offen |

## Dashboard

| ID | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|
| D-1 | hoch | Abhaken einer Aufgabe/eines Ämtli: kein optimistischer Zustand (`:checked="false"`), keine Rückmeldung, kein Fehler-Handling; `toggleDone` *kippt* den Zustand – Doppeltipp öffnet die Aufgabe wieder. | Lokales `completingIds`, explizit `is_done: true`, Toast „Erledigt“ mit Undo, Fehler-Toast. | ✅ |
| D-2 | hoch | Ladefehler wird nur geloggt; Seite zeigt nur die Begrüssung. | Fehlerzustand mit „Erneut versuchen“. | ✅ |
| D-3 | gering | Schnell-Chips mit Nomen („Einkauf“, „Aufgabe“). | Verben („Artikel erfassen“ …). | ✅ |
| D-4 | gering | Leere Aufgaben-Karte ohne CTA; `BaseCheckCircle` ohne zugänglichen Namen. | Link „Aufgabe erfassen“, `aria-label`. | ✅ |

## Einkauf

| ID | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|
| E-1 | hoch | Listen laden ohne Ladezustand → „Erste Liste erstellen“ blitzt auf; Ladefehler zeigt denselben Leerzustand. | Lade-/Fehlerzustand für Listen. | ✅ |
| E-2 | hoch | Neu angelegte Liste wird nicht ausgewählt; bei der ersten Liste bleibt die Seite leer. | Neue Liste aktiv setzen. | ✅ |
| E-3 | hoch | „Erledigte entfernen“: Fehler verschluckt, trotzdem „Liste geleert“; Undo legt die Artikel *offen* (statt abgehakt) und ggf. in der falschen Liste wieder an. | `allSettled`, Fehler melden, Undo mit Original-Liste und `is_checked`. | ✅ |
| E-4 | hoch | Quick-Add leert das Feld vor dem Request; bei Fehler/offline ist der Text weg. | Offline-Sperre, Text bei Fehler wiederherstellen. | ✅ |
| E-5 | mittel | Undo nach Löschen verliert `is_checked`, Zuweisung, Liste. | Vollständiger Snapshot. | ✅ |
| E-6 | mittel | Offene Artikel lassen sich nicht löschen (nur im Erledigt-Bereich). | „Löschen“ im Bearbeiten-Sheet mit Undo. | ✅ |
| E-7 | mittel | Bearbeiten-Sheet, „Neue Liste“, Umbenennen/Auflösen Geschäft: kein Doppelklick-Schutz; Umbenennen/Auflösen schliessen auch bei Fehler. | Pending-Guard, nur bei Erfolg schliessen. | ✅ |
| E-8 | mittel | Listen umbenennen/löschen: Store und Texte vorhanden, aber keine UI. | Menü an der Listen-Pille. | ✅ |
| E-9 | mittel | Zusammenführen-Bestätigung per `window.confirm`. | Zweiter Schritt im Dialog. | ✅ |
| E-10 | mittel | „Liste leeren“ klingt nach ganzer Liste, entfernt aber nur Erledigte. | „Erledigte entfernen“. | ✅ |
| E-11 | mittel | Ladefehler Artikel → „Keine offenen Artikel“. | Fehlerzustand. | ✅ |
| E-12 | gering | „+“-Pille, Zuweisen-, Kebab-Button ohne `aria-label`; Store-Eingabe 14 px (iOS-Zoom); dauerhaftes `autofocus` öffnet bei jedem Tab-Besuch die Tastatur. | Labels, 16 px, Autofokus nur bei `?new=1`. | ✅ |

## Aufgaben

| ID | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|
| A-1 | hoch | Mit aktivem Personen-Filter verschwindet eine neu angelegte Aufgabe sofort (unzugewiesen → ausgefiltert). | Filter-Person vorbelegen bzw. Hinweis-Toast. | ✅ |
| A-2 | hoch | Bei Fehler beim Anlegen sind Titel, Beschreibung, Datum, Erinnerungen schon zurückgesetzt. | Erst nach Erfolg zurücksetzen. | ✅ |
| A-3 | mittel | Erinnerungen werden an `items[length-1]` gehängt; nach Socket-Refetch evtl. an die falsche Aufgabe. | ID aus `addTodo` verwenden. | ✅ |
| A-4 | mittel | Ganze Zeile hakt ab; versehentliches Tippen erledigt ohne Undo, Eintrag verschwindet im eingeklappten Bereich. | Toast „Erledigt“ mit Undo. | ✅ |
| A-5 | mittel | Undo nach Löschen verliert Tags, Erinnerungen. | Vollständiger Snapshot. | ✅ |
| A-6 | mittel | Ladefehler → „Keine offenen Aufgaben“. | Fehlerzustand. | ✅ |
| A-7 | mittel | Bearbeiten: kein Fokus auf Titel, Escape bricht nicht ab, leerer Titel still ignoriert; Eingaben 14 px. | Fokus, Escape, Inline-Fehler, 16 px. | ✅ |
| A-8 | mittel | Jedes Socket-Event lädt alle Aufgaben neu und überschreibt laufende optimistische Änderungen. | Store-Handler nutzen, Refetch nur bei Reconnect. | ✅ |
| A-9 | gering | Erinnerung-entfernen-Buttons ohne `aria-label`; „▸/▾“ als Text ohne `aria-expanded`. | Labels. | ✅ |

## Ämtli

| ID | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|
| C-1 | mittel | Ein `loading`-Flag für zwei parallele Requests; Skeleton erscheint bei jedem Neuladen über bestehendem Inhalt. | Skeleton nur ohne Daten. | ✅ |
| C-2 | mittel | „Keine Aufgaben diese Woche“ + CTA „Erstes Ämtli anlegen“ auch wenn Ämtli existieren. | CTA nur ohne Ämtli; Text „Keine Ämtli diese Woche“. | ✅ |
| C-3 | mittel | CTA öffnet das Formular weit unten ohne Scroll/Fokus – wirkt wirkungslos. | `scrollIntoView` + Fokus. | ✅ |
| C-4 | mittel | Ladefehler → „Noch keine Ämtli definiert“. | Fehlerzustand. | ✅ |
| C-5 | mittel | Abhaken eines Ämtli ohne Bestätigung „Ämtli erledigt“ für andere Wochen ausser Sicht; Umverteilen ohne Pending-Guard. | Toast mit Undo, Guard. | ✅ |
| C-6 | mittel | Löschen in Inline-Bestätigung ohne Loading. | Guard. | ✅ |
| C-7 | mittel | Monatstag-Validierung nur als Toast. | Inline-Fehler. | ✅ |
| C-8 | gering | `aria-label` „↑“/„↓“; Titel „Putzplan“ vs. „Ämtli“; „+“ im Text. | Klartext, einheitlich „Ämtli“. | ✅ |

## Ausgaben, Ausgleich, Budget, Rechnungen

| ID | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|
| F-1 | hoch | Ladefehler Ausgaben → „Erfasse oben eine neue Ausgabe“; Budget-Ladefehler → „Kein Budget gesetzt CHF 0.00“. | Fehlerzustände mit Retry. | ✅ |
| F-2 | hoch | Budget-Übersicht („Noch verfügbar“, Balken) wird nach Anlegen/Ändern/Löschen einer Ausgabe nicht aktualisiert. | `fetchSummary` nach Ausgaben-Änderungen. | ✅ |
| F-3 | hoch | Standarddatum Ausgabe/Ausgleich in UTC (nachts gestern, ggf. falscher Monat). | Lokales Datum. | ✅ |
| F-4 | mittel | Betragsfehler erst beim Absenden, Button nur grau ohne Erklärung. | Inline-Validierung bei Blur. | ✅ |
| F-5 | mittel | Formularfehler zeigt rohes `detail` (oft Englisch). | `errorText`. | ✅ |
| F-6 | mittel | Nach Speichern kein Feedback; neue Ausgabe auf Mobile oft unter dem Falz. | Toast „Ausgabe gespeichert“. | ✅ |
| F-7 | mittel | `?new=1` öffnet Formular, bevor Mitglieder geladen sind → Zahler/Teilnehmer leer, Speichern unmöglich. | Mitglieder nachziehen. | ✅ |
| F-8 | mittel | Eigene Overlays (Ausgabe, Ausgleich) statt `BaseDialog`: kein Escape, keine Zurück-Taste, kein Fokus. | Auf `BaseDialog` umstellen. | ✅ |
| F-9 | mittel | Löschen ohne Pending-Guard; Undo legt neue Ausgabe an (verliert Kategorie/Rechnungs-Bezug). | Guard; Undo mit Kategorie. Echte Wiederherstellung braucht Backend. | ◐ teilweise |
| F-10 | mittel | Rechnung buchen ohne Undo, obwohl Zahler leicht falsch gewählt ist. | Undo = gebuchte Ausgabe löschen. | ✅ |
| F-11 | mittel | Budget speichern: Enter kann doppelt senden, Fehler nur Toast „Fehler“, kein Fokus beim Bearbeiten. | Guard, Inline-Fehler, Fokus. | ✅ |
| F-12 | mittel | Ladefehler Salden → Karte verschwindet still. | Fehlerzustand. | ✅ |
| F-13 | gering | Leerzustand ohne CTA, „Kein Budget gesetzt“ doppelt, „Alle gebucht“ widersprüchlich, `aria-label` als Frage, `ExpenseList.vue` ungenutzt. | Copy/Aufräumen. | ✅ |

## Kalender, Abstimmungen

| ID | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|
| K-1 | hoch | `toast.show(...)` existiert nicht – jeder Fehlerpfad (Termin anlegen/ändern/löschen, Abstimmen, Entscheiden, Kalender löschen) wirft im `catch` einen TypeError; Nutzer sieht nichts. | `notifyError`. | ✅ |
| K-2 | hoch | Ladefehler beim Öffnen: Socket-Listener werden nicht registriert (Echtzeit tot), kein Fehlerzustand. | Listener zuerst, `allSettled`, Fehlerzustand. | ✅ |
| K-3 | hoch | Abstimmung „Übernehmen“: Karte verschwindet, Termin ausserhalb der Ansicht – keine Rückmeldung. | Toast mit Datum. | ✅ |
| K-4 | hoch | Nach Entscheiden lädt `fetchEvents()` die Woche, auch in der Monatsansicht → Monat verliert Termine. | Tab-abhängig neu laden. | ✅ |
| K-5 | mittel | Essens-Abstimmungen erscheinen im Kalender mit „Termin übernehmen“. | Im Kalender ausfiltern. | ✅ |
| K-6 | mittel | Kalender hinzufügen/umbenennen/Farbe: keine Fehlermeldung, kein Feedback. | `run()` mit vorhandenen Texten. | ✅ |
| K-7 | mittel | Neuer Termin ausserhalb der sichtbaren Woche: nichts passiert sichtbar. | Toast mit Datum. | ✅ |
| K-8 | mittel | Kein Skeleton/Fehlerzustand. | Skeleton, Fehlerzustand. | ✅ |
| K-9 | mittel | Tab „Liste“ zeigt nur den zuletzt geladenen Bereich ohne Hinweis. | Eigener Bereich (z. B. 60 Tage) – eigenes Vorhaben. | ⏳ offen |
| K-10 | mittel | Abstimmen ohne Pending-Guard; gleiche Option erneut sendet Request. | Guard, früher Ausstieg. | ✅ |
| K-11 | mittel | Enter sendet das Termin-Formular nicht (Button ausserhalb des Formulars). | `form`-Attribut. | ✅ |
| K-12 | mittel | Termin/Kalender löschen per `confirm()`. | Termin: Undo statt Bestätigung; Kalender: Dialog. | ✅ |
| K-13 | mittel | Keine UI zum Anlegen/Löschen von Termin-Abstimmungen (Texte vorhanden). | Eigenes Vorhaben. | ⏳ offen |
| K-14 | gering | Leertext ohne CTA und unpassend („heute“ für andere Tage), `aria-label` „Next week“ hartkodiert, „+“ ohne Label, Kalendername 14 px. | Copy, Labels, 16 px. | ✅ |

## Haustiere

| ID | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|
| H-1 | hoch | „Katze hinzugefügt“/„gelöscht“ als **Fehler**-Toast (Typ fehlt). | Typ `success`. | ✅ |
| H-2 | hoch | Füttern: Store schluckt Fehler, Toggle springt still zurück; „Alle gefüttert“ ohne Feedback, Loading, Guard. | Fehler weiterreichen, Toast „Gefüttert“/„Alle gefüttert“ mit Undo. | ✅ |
| H-3 | hoch | Geleerte Felder (Rasse, Chip, Tierarzt, Gewicht, Dosis …) werden als `undefined` gesendet und bleiben gespeichert; alle Gesundheitseinträge entfernen löscht nichts. | `null` bzw. `[]` senden. | ✅ |
| H-4 | hoch | Medikamente/Pflegeaufgaben beim Tierwechsel nicht zurückgesetzt; bei Ladefehler zeigt Tier B die Medikamente von Tier A. | Listen leeren, `watch(petId)`. | ✅ |
| H-5 | mittel | „Jetzt geben“: kein Guard, Doppeltipp = zwei Gaben. | Guard. Undo braucht Backend-DELETE (offen). | ◐ teilweise |
| H-6 | mittel | Pflegeaufgabe erledigen ohne Mutex/Loading, ohne Undo. | Guard. | ◐ teilweise |
| H-7 | mittel | Ungültiges Intervall/Gewicht: still bzw. nur Toast. | Inline-Fehler. | ✅ |
| H-8 | mittel | Füttern-Buttons ohne `aria-pressed`, Label nur „Morgen“. | `aria-pressed`, „Morgens“/„Abends“. | ✅ |
| H-9 | mittel | Generische „Fehler“-Toasts bei Medikament/Pflege. | Spezifische Texte. | ✅ |
| H-10 | mittel | Nicht gefunden vs. Netzwerkfehler nicht unterscheidbar. | Fehlerzustand mit Retry. | ✅ |
| H-11 | mittel | Anlegen: keine Tierart-Auswahl. | Eigenes Vorhaben. | ⏳ offen |
| H-12 | gering | Modul heisst „Katzen“, unterstützt aber mehrere Arten; Kamera-Button-Label „Foto wird hochgeladen…“. | Copy. | ◐ teilweise |

## Pflanzen

| ID | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|
| P-1 | hoch | **Auslöser:** „Gegossen“ ohne jede Rückmeldung, Button ohne Loading. | Toast „{Name} gegossen“ mit Undo, `:loading`. | ◐ teilweise |
| P-2 | hoch | Detailseite: Ladefehler → „Pflanze nicht gefunden“. | Fehlerzustand mit Retry. | ✅ |
| P-3 | mittel | „Erledigt“ ohne Loading und Undo. | `:loading`, Undo. | ◐ teilweise |
| P-4 | mittel | Fehler beim Pflegestatus still → Badges und „Alle giessen“ verschwinden. | Status behalten. | ✅ |
| P-5 | mittel | Intervall-Fehler nur als Toast. | Inline-Fehler. | ✅ |
| P-6 | mittel | Aufgabe löschen: Bestätigung ohne Text, ohne Loading; Pflanze löschen nur in der Liste. | Text/Guard. | ◐ teilweise |
| P-7 | mittel | Speichern ohne `:loading`, kein Fokus auf Name. | `:loading`, Fokus (BaseDialog). | ✅ |
| P-8 | gering | „Alle fälligen giessen“ ohne Undo; Pflegehinweise einzeilig. | Undo, Textarea. | ◐ teilweise |
| P-9 | gering | „Gießen“ mit ß (Schweizer Schreibweise „giessen“). | ss. | ✅ |

## Essen, Rezepte, Wochenplan

| ID | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|
| M-1 | hoch | Kein `useToast` importiert: Zuweisen, Entfernen, Auf Einkaufsliste, Favorit, Abstimmung starten/entscheiden, Abstimmen scheitern alle still. | Fehlermeldungen überall. | ✅ |
| M-2 | hoch | Keine UI zum Anlegen/Bearbeiten/Löschen von Rezepten; ohne KI ist „Rezept auswählen“ leer. | Eigenes Vorhaben (Rezept-Verwaltung). | ⏳ offen |
| M-3 | hoch | „Entscheiden“ entscheidet für den ganzen Haushalt ohne Bestätigung und ohne Rückmeldung; Gleichstand nimmt still die erste Option. | Bestätigung mit Gewinner, Toast. | ✅ |
| M-4 | mittel | „Entfernen“ eines geplanten Essens ohne Undo. | Undo. | ✅ |
| M-5 | mittel | „Auf Einkaufsliste“: Inline-Erfolg verschwindet, kein Link, Fehler still. | Toast mit „Zur Liste“. | ✅ |
| M-6 | mittel | Favorit nicht optimistisch, kein Guard; Abstimmung starten ohne Guard (Doppeltipp = 2 Abstimmungen). | Guards. | ✅ |
| M-7 | mittel | Wochenwechsel-Race: alte Antwort überschreibt aktuelle Woche. | Antwort verwerfen, wenn Woche nicht mehr aktuell. | ✅ |
| M-8 | mittel | „Gericht zuweisen“ öffnet zweiten Dialog über dem ersten. | Erst schliessen. | ✅ |
| M-9 | mittel | Selects 12–14 px (iOS-Zoom). | 16 px. | ✅ |
| M-10 | gering | Wochentage hartkodiert Deutsch, „Next week“ hartkodiert, Icon-Buttons ohne Label. | i18n. | ✅ |

## Notizen

| ID | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|
| N-1 | hoch | Quick-Add leert das Feld vor dem Request; bei Fehler ist der Text weg. | Erst nach Erfolg leeren. | ✅ |
| N-2 | hoch | Bearbeiten-Dialog: Overlay/Escape/Zurück verwerfen bis zu 5000 Zeichen ohne Rückfrage; kein „Abbrechen“. | Rückfrage bei Änderungen. | ✅ |
| N-3 | mittel | Löschen per `confirm()`, obwohl der Store optimistisch ist. | Sofort löschen + Undo. | ✅ |
| N-4 | mittel | Pin-Button: Label ist Zustand („Angepinnt“), kein `aria-pressed`. | „Anpinnen“/„Lösen“. | ✅ |
| N-5 | gering | Leerzustand ohne CTA, Quick-Add ohne Label. | CTA, Label. | ✅ |

## Dokumente

| ID | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|
| DOK-1 | hoch | Ladefehler: Toast und danach „Noch keine Dokumente“. | Fehlerzustand. | ✅ |
| DOK-2 | mittel | Löschen per `confirm()`, ohne Erfolgs-Toast. | Dialog bzw. Toast. | ✅ |
| DOK-3 | mittel | Metadaten speichern/Seiten hinzufügen ohne Rückmeldung. | Toast. | ✅ |
| DOK-4 | mittel | Upload/Speichern offline nicht gesperrt. | Offline-Sperre. | ✅ |
| DOK-5 | mittel | Vorschau-Dialog leer bei Fehler. | Fehlertext. | ✅ |
| DOK-6 | gering | Leerzustand ohne CTA; Suche nur im Titel, Platzhalter suggeriert Volltext. | CTA, Copy. | ✅ |

## Haushalt, Mitglieder, Einladung

| ID | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|
| HH-1 | hoch | Mitglieder-Ladefehler → „Keine Mitglieder geladen.“, kein Ladezustand. | Lade-/Fehlerzustand. | ✅ |
| HH-2 | hoch | Haushalt verlassen: Socket-Event zeigt zusätzlich „Du wurdest entfernt“ (falsch), bis zu 3 Toasts; ohne Socket bleibt man auf der Seite des verlassenen Haushalts. | Eigene Austritte nicht als Entfernung melden, explizit navigieren. | ✅ |
| HH-3 | mittel | „Verlassen“ lädt erst Salden ohne Loading. | `:loading`. | ✅ |
| HH-4 | mittel | Saldo-Warnung ohne Richtung („Du hast noch offene …“). | „Du schuldest …“/„Dir stehen … zu“. | ✅ |
| HH-5 | mittel | Code neu erzeugen per `confirm()`. | Dialog. | ✅ |
| HH-6 | mittel | Teilen-Text enthält nur den Code, keinen Link. | Link `/register?code=…`. | ✅ |
| HH-7 | mittel | Push-Test ohne Rückmeldung. | Toast „Test gesendet“. | ✅ |
| HH-8 | gering | Umbenennen: Enter sendet nicht; Fehler ohne Code; nach Anlegen/Beitreten Landung auf `/shopping` statt Start. | Form, `notifyError`, `/dashboard`. | ✅ |

## Tags und Scan

| ID | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|
| T-1 | hoch | Ladefehler → „Noch keine Tags“. | Fehlerzustand. | ✅ |
| T-2 | mittel | Leerzustand ohne CTA (Admins). | „Tag anlegen“. | ✅ |
| T-3 | mittel | Token neu/Löschen per `confirm()`. | Dialog. | ✅ |
| T-4 | mittel | Label speichern/Aktivieren ohne Feedback, Buttons ohne Spinner. | Toast, `:loading`. | ✅ |
| T-5 | mittel | Scan-Erfolgsseite ohne Undo. | Braucht Backend (offen). | ⏳ offen |
| T-6 | gering | `translateApiError(err) \|\| t(...)` – Fallback greift nie. | `notifyError`. | ✅ |

## KI-Assistent

| ID | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|
| KI-1 | mittel | Offline/Netzfehler beim Status → „auf diesem Server nicht eingerichtet“ (falsch); während des Ladens leer. | Lade-/Fehlerzustand. | ✅ |
| KI-2 | gering | Unbekannter Fehlercode zeigt rohen Key; Einstellungen-Link auch für Nicht-Admins. | `te()`-Fallback. | ✅ |

## Login, Registrierung, Logout

| ID | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|
| L-1 | hoch | Sitzung abgelaufen → stiller Sprung auf Login; vorhandener Text `auth.sessionExpired` ungenutzt. | Hinweis auf der Login-Seite. | ✅ |
| L-2 | mittel | Leeres Formular/zu kurzes Passwort/ungültige E-Mail → englische Pydantic-Meldungen. | Client-Validierung, 422-Mapping. | ✅ |
| L-3 | mittel | Wechsel Login↔Registrierung verliert `?redirect` (Tag-Scan als Neuling). | `redirect` weiterreichen. | ✅ |
| L-4 | gering | Nach Login/Registrierung Landung auf `/shopping`, sonst überall `/dashboard`; kein Autofokus. | `/dashboard`, Autofokus. | ✅ |
| L-5 | gering | Logout ohne Bestätigung (offline faktisch nicht umkehrbar). | Bestätigung nur offline. | ✅ |

## UX-Copy (Locales)

| ID | Schwere | Befund | Vorschlag | Status |
|---|---|---|---|---|
| CP-1 | gering | „ß“ statt „ss“ (Giessen, giessen, Giessaufgabe). | Schweizer Schreibweise. | ✅ |
| CP-2 | gering | Unpersönliche Infinitive („Bitte einen gültigen Betrag eingeben“, „bitte nochmals versuchen“) neben Du-Form. | Durchgehend Du-Form. | ✅ |
| CP-3 | gering | „Invite-Code“ neben „Einladungscode“; Ausrufezeichen in Erfolgsmeldungen; „+“ in Button-Texten; „z.B.“ vs. „z. B.“. | Vereinheitlichen. | ✅ |
| CP-4 | gering | Generische Fehler („Fehler“, „Ein Fehler ist aufgetreten“). | Was ist schiefgegangen. | ◐ teilweise |
| CP-5 | gering | EN: Title Case gemischt („Edit Note“, „All Notes“). | Sentence case. | ✅ |

## Offen und warum

| ID | Was fehlt | Warum nicht in diesem Branch |
|---|---|---|
| P-1, P-3, P-8, H-5, H-6 | „Rückgängig“ nach Gegossen, Pflege erledigt, Alle giessen, Medikament gegeben, Tier-Pflege erledigt. Rückmeldung, Ladezustand und Doppelklick-Schutz sind umgesetzt. | Das Backend hat keinen Endpunkt zum Löschen eines Pflege-Log- bzw. Medikamenten-Eintrags. Das Löschen müsste auch die nächste Fälligkeit zurückrechnen. Eigenes Backend-Vorhaben. |
| T-5 | Rückgängig auf der Scan-Erfolgsseite | Gleicher Grund (Tag-Aktionen schreiben Pflege-/Fütterungs-Logs). |
| F-9 | Undo nach Löschen einer Ausgabe stellt den Bezug zur gebuchten Rechnung nicht wieder her (neue Ausgabe statt Wiederherstellung). | Braucht einen Restore-Endpunkt oder Soft-Delete im Backend. Gleiches gilt grundsätzlich für alle Undo-nach-Löschen (Einkauf, Aufgaben, Notizen, Termine): sie legen den Eintrag mit allen Feldern neu an (neue ID, neues Erstelldatum). |
| P-6 | Pflanze löschen auch in der Detailansicht | Neue Funktion, nicht nur Feedback. |
| H-11, H-12 | Tierart-Auswahl beim Anlegen; Modul heisst weiter „Katzen“ | Der Name folgt dem Funktionsumfang; erst mit Tierart-Auswahl umbenennen. |
| M-2 | Rezepte anlegen/bearbeiten/löschen ohne KI | Eigenes Feature (Rezept-Verwaltung). |
| K-9 | Listen-Tab im Kalender mit eigenem Zeitraum | Eigenes Feature. |
| K-13 | Termin-Abstimmungen im Kalender anlegen/löschen | Eigenes Feature. |
| Q-18 | Typecheck prüft in CI nichts | Werkzeug-Thema mit ~170 Altfehlern, eigenes Vorhaben (vue-tsc aktualisieren, `-b`). |
| CP-4 | Einzelne generische Texte („Fehler“) bestehen noch an Stellen ohne eigene Meldung | Gering; die meisten Aktionen haben jetzt spezifische Texte oder den übersetzten Fehlercode. |

## Prüfung

- Vitest: 411 Tests grün (neu: Toast-Helper, Undo, `useAsyncAction`, `useLoader`, `localDateString`, Fehlerübersetzung, Store-Logik für Wiederherstellen/Undo).
- Browser (Playwright, Chromium, 390 × 844, Backend mit SQLite): Login, alle 14 Seiten ohne JS-Fehler; „Gegossen“ zeigt „{Name} gegossen“; offline erscheint „Du bist offline – die Änderung wurde nicht gespeichert.“ statt eines Requests; mit HTTP 500 zeigen alle Listen „Laden hat nicht geklappt … Erneut versuchen“ statt eines Leerzustands; Zurück schliesst Dialog und Mehr-Sheet ohne die Seite zu verlassen; „Mehr“ → Notizen navigiert korrekt; Rückfrage „Änderungen verwerfen?“ mit „Weiter bearbeiten“; Escape schliesst nur den obersten Dialog; unbekannte URL → Start.

## Ausserhalb des Scopes (nur notiert)

| Bereich | Fund | Zuständig |
|---|---|---|
| Layout | Offline-Banner (fixed, z-index 9999) überdeckt Top-Bar/PageHeader. | `claude/mobile-layout-fixes` |
| Layout | Toasts überdecken auf Mobile den FAB (rechts unten). | `claude/mobile-layout-fixes` |
| Layout | Kategorie-Chips und Ausgleichs-Zeilen mit `nowrap` können bei 320 px überlaufen. | `claude/mobile-layout-fixes` |
| Layout | Touch-Ziele < 44 px: `.action-btn` 32 px (Aufgaben, Ämtli), `BaseCheckCircle` 22 px, Schweregrad-Punkte 18 px (Haustiere), `.book-select` 40 px. | `claude/mobile-layout-fixes` |
| Design-System | `ExpenseFormDialog`/`BalanceSummary` nutzen alte Tokens (`--color-surface`, `--color-neutral-300`). | `claude/ui-design-audit` |
| Design-System | `ShoppingView` mit eigenen `.btn-primary`/`.pill-tab` statt `BaseButton`/`BasePillTabs`. | `claude/ui-design-audit` |
| Design-System | `BaseButton variant="outline"` existiert nicht (FoodView) → ungestylt. | `claude/ui-design-audit` |
| Design-System | Inline-Styles in Skeletons und Dashboard-Icons. | `claude/ui-design-audit` |
