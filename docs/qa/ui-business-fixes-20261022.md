# UI/UX und Geschäftslogik: Korrekturen vom 22. Oktober 2026

Dieser Bericht beschreibt die Korrekturen aus dem UI-/Geschäftslogik-Audit und die lokale Abnahme vor dem Release. Drei Hilfsagenten bearbeiteten Dateiverwaltung/CORS, Finanzformular sowie Verlauf/Haushaltszeit; anschliessend wurden die Änderungen gegenseitig und in gemeinsamen Browserabläufen geprüft. Die [Sicherheitskorrekturen vom 21. Oktober](../security/audit-remediation-2026-10-21.md) bleiben ein eigener Bestandteil desselben Release-Zweigs.

## Korrigiertes Verhalten

| Bereich | Verhalten nach der Korrektur |
|---|---|
| B01 Dateibereinigung | Neue Speicherschlüssel verwenden `/`. Lesen, Löschen und Waisenbereinigung erkennen auch bestehende Windows-Schlüssel mit Backslash. Registrierte Dateien werden dadurch nicht irrtümlich als verwaist entfernt; Pfadbegrenzungen bleiben erhalten. Bestehende Datenbankwerte müssen nicht migriert werden. |
| B02 Individuelle Kostenanteile | Jedes ausgefüllte Anteilsfeld wird validiert. Negative oder ungültige Werte sperren Speichern und erhalten eine zugänglich verknüpfte Fehlermeldung. Leer und null bedeuten keinen Anteil; die Summe muss weiterhin dem Gesamtbetrag entsprechen. Berechnungen erfolgen in ganzzahligen Rappen. |
| B03 Bearbeitung über CORS | Der Preflight erlaubt `If-Match` für konfigurierte Ursprünge. Die Versionsprüfung bleibt aktiv; fremde Ursprünge werden weiterhin abgelehnt. |
| B04 Gelöschte Finanzeinträge | Ausgaben und Ausgleiche lassen sich über eine gemeinsame Aktion weiter nachladen. Stabile Sortierung, ID-Deduplizierung und erneutes Laden des bereits sichtbaren Bereichs halten den Verlauf nach Löschen/Wiederherstellen konsistent. Fehler bieten Wiederholen; vorhandene Zeilen bleiben sichtbar. Auch Löschungen während der ersten Anfrage werden berücksichtigt. |
| B05 Ungespeicherte Ausgaben | Schliessen, Abbrechen, Escape, Hintergrundklick und Browser-Zurück fragen bei Änderungen vor dem Verwerfen nach. Weiterbearbeiten erhält den Entwurf. Verschachtelte Dialoge stellen Fokus und Browser-History in kontrollierter Reihenfolge wieder her. |
| B06 Gleichzeitiges Bearbeiten | HTTP 409 erhält den Entwurf und zeigt den aktuellen Datensatz. Der Nutzer kann den Serverstand laden oder eigene Änderungen bewusst übernehmen. Unveränderte Felder werden aus dem aktuellen Datensatz übernommen; bei tatsächlich beidseitig geänderten Feldern gewinnen nach dieser Auswahl die eigenen Werte. Das anschliessende Speichern verwendet erneut `If-Match`. |
| B07 Haushaltszeit | Standardwoche im Essensplan, Heute-Markierung und Abstimmungsdatum richten sich nach der Haushaltszeitzone. Die Kalenderarithmetik ist unabhängig von Gerätezeitzone und Sommerzeitwechsel. |

Beim Zusammenführen eines Ausgabenentwurfs gelten `100` und `100.00` als gleicher Geldbetrag. Aufteilungsart, Teilnehmer und individuelle Anteile werden gemeinsam übernommen, damit keine fachlich widersprüchliche Teilaufteilung entsteht. Ungültige Eingaben bleiben korrigierbar und werden nicht stillschweigend entfernt.

Zusätzlich wurden das zweispaltige Desktop-Dashboard samt Kopfzeile, die eindeutige Fütterungsanzahl, das umbrechende E-Mail-Bestätigungsbanner und zugängliche Anteilslabels umgesetzt. Dialogkopf und Aktionen bleiben sichtbar, während nur der Inhalt scrollt. Der Kartenkopf für wiederkehrende Rechnungen bricht bei schmalen Ansichten um.

Die Release-Gegenprüfung fand zusätzlich abgeschnittene Aktionen in verschachtelten Dialog-Footergruppen für Essen, Kalender und Haustiere; diese Gruppen brechen jetzt um, sodass auch längere Beschriftungen erreichbar bleiben.

## Bedienung und Abnahmeabläufe

1. **Entwurf behalten:** Ausgabe bearbeiten, einen Wert ändern und schliessen. «Weiter bearbeiten» wählen und die Eingaben kontrollieren. Zum Verwerfen erneut schliessen und bestätigen; der Fokus kehrt zum ursprünglichen Auslöser zurück.
2. **Konflikt auflösen:** Dieselbe Ausgabe in zwei Sitzungen öffnen. In der zweiten Sitzung speichern, dann den älteren Entwurf speichern. Den angezeigten aktuellen Datensatz prüfen und bewusst «Meine Änderungen übernehmen» oder den Serverstand wählen. Nach dem Zusammenführen kontrollieren und erneut speichern.
3. **Ältere Löschungen finden:** Im Finanzverlauf «Weitere Einträge laden» wählen. Einen älteren Eintrag wiederherstellen und prüfen, dass er aus dem Verlauf verschwindet und wieder in der jeweiligen aktiven Liste erscheint. Bei Ladefehlern die sichtbare Wiederholungsaktion verwenden.
4. **Haushaltsdatum prüfen:** Mit abweichender Gerätezeitzone den Essensplan nahe Mitternacht öffnen. Woche, Heute-Markierung und Vorgabedatum einer neuen Abstimmung müssen dem Datum des Haushalts entsprechen.

## Lokale Prüfergebnisse

Stand: 22. Oktober 2026, Windows, Chromium, synthetische Konten und isolierte SQLite-Datenbank.

| Prüfung | Ergebnis |
|---|---|
| Backend-Gesamtlauf | 1265 bestanden, 81 übersprungen, keine fehlgeschlagen; 156 Warnungen. |
| Frontend mit Coverage | 859 Tests in 64 Dateien bestanden; Statements 82,50 %, Branches 76,99 %, Lines 84,85 %. Der abschliessende Release-Lauf enthält auch die Dialog-History- und Footer-Korrekturen; ergänzend wurden Browserregression und CSS-Integration geprüft. |
| Build und statische Prüfung | Produktionsbuild, App-Typprüfung, Abgleich aller 1462 deutschen/englischen Übersetzungsschlüssel, Backend-Ruff und `git diff --check` bestanden. |
| Responsive Routen | 13 Ansichten bei 320, 393, 768, 1024 und 1440 Pixeln: 65 tatsächliche Seitenaufrufe mit Inhaltsprüfung, ohne JavaScript-Ausnahmen oder horizontalen Überlauf. |
| Finanzformular | Ungültige Anteile, Entwurfserhalt, Fokus, echter HTTP-409-Konflikt, kontrolliertes Zusammenführen und wiederholtes Browser-Zurück geprüft. Kopf und Aktionen bei 320 × 568 und 393 × 480 vollständig sichtbar. |
| Verlauf | 51 gelöschte Ausgaben und 51 gelöschte Ausgleiche: zunächst 100 sichtbar, nach Nachladen 102, nach Wiederherstellung je eines Eintrags 100. API-Zustände bestätigt. |
| Datum | Browser in Los Angeles bei `2026-10-25T23:30Z`: Zürcher Haushalt zeigt die Woche ab 26. Oktober; die tatsächlich gespeicherte Abstimmung verwendet ebenfalls den 26. Oktober. |
| Englisch und dunkles Theme | Dashboard visuell geprüft; Finanzdialog bei vier Breiten ohne horizontalen Überlauf, Fokus bleibt mit Tab/Shift+Tab im Dialog. Keine fehlenden Übersetzungen oder JavaScript-Ausnahmen im geprüften Ablauf. |
| Dateibereinigung | Eigenständige Windows-Gegenprobe mit sechs Assertions: alte registrierte Dateien beider Pfadformate bleiben erhalten, nur alte unbekannte Dateien werden entfernt; frische Dateien bleiben erhalten. |
| Dialog-Footer-CSS | Isolierte Chromium-Fixtures mit den tatsächlichen Theme-/Dialog-/Button-/View-CSS und deutschen/englischen Beschriftungen: neun Footerbeispiele bei 320, 393 und 768 Pixeln, insgesamt 54 Kombinationen. Vorher reproduzierte Abschneidungen in Essen/Kalender/Haustieren; danach alle Aktionen innerhalb des Panels. Dies ist eine CSS-Integrationsprüfung, kein authentifizierter Gesamtappablauf. |

Die Regressionstests für Pfade und Verlauf stehen in [`backend/tests/test_storage_paths.py`](../../backend/tests/test_storage_paths.py) und [`backend/tests/test_finance_history_pagination.py`](../../backend/tests/test_finance_history_pagination.py). Frontendtests liegen unter [`frontend/src/utils/__tests__/`](../../frontend/src/utils/__tests__/) und [`frontend/src/stores/__tests__/`](../../frontend/src/stores/__tests__/). Die regulären Testbefehle stehen im [README](../../README.md#prüfungen-wie-in-der-ci). Die ergänzenden lokalen Browserprotokolle und Screenshots sind nicht Bestandteil des Repositorys.

## Grenzen und Deployment

Diese Ergebnisse belegen die lokale Abnahme, kein Deployment. Produktive Daten wurden dabei nicht verändert. Die PostgreSQL-Testlane war lokal nicht verfügbar; ein zusätzlicher Symlink-Test wurde mangels Windows-Berechtigung übersprungen. Python lief lokal mit 3.13 statt der dokumentierten 3.12. Echtes iPhone/Safari, native Bildschirmtastatur und Live-Anbieter wurden nicht geprüft. CI- und Deployment-Ergebnisse sind gesondert am jeweiligen Release-Commit nachzuweisen.

Frontend und Backend gemeinsam aktualisieren. Diese UI-/Geschäftslogik-Korrekturen fügen **keine neue Migration** hinzu. Der gesamte Release-Zweig enthält jedoch weiterhin die frühere Sicherheitsmigration `b4c5d6e7f8a9`; ein Update von einem älteren Stand ist deshalb nicht pauschal migrationsfrei. Voraussetzungen, Backup und Betriebsprüfung stehen in der [Deployment-Anleitung](../deployment.md#3-update-prozedur).
