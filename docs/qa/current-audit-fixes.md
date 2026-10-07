# Korrekturen zum Audit vom 7. Oktober 2026

Die Korrekturen basieren auf dem aktuellen `master`-Commit `564f071` und liegen auf `fix/current-audit-20261007`.
Der frühere Branch mit Änderungen am veralteten Stand wurde nicht übernommen.

## Ergebnisse

| Befund | Korrektur | Nachweis |
|---|---|---|
| Leere Katzenseite | Fehlenden Auth-Store importiert und initialisiert. | Katzenseite über „Mehr“ und direkte Navigation geöffnet; keine JavaScript-Ausnahme. |
| Unwirksame Typprüfung | `typecheck` prüft ausdrücklich `tsconfig.app.json`; der Build ruft diese Prüfung auf. Vue-Augmentation ist ein eigenes TypeScript-Modul. Verbleibende Typfehler in Dokumentenaktion und Testdaten korrigiert. | App-Typprüfung und Produktionsbuild bestehen. |
| Doppelte Medikamentengabe in der Anzeige | HTTP- und Socket-Antwort werden über dieselbe Log-ID zusammengeführt; Antworten für verlassene Haushalte werden verworfen. | Tests für beide Antwortreihenfolgen; im Browser ein Eintrag vor und nach Reload. |
| HEIC hängt von einem Browserdecoder ab | Erst `createImageBitmap`, danach HTML-Image-Decoder; anschließend Canvas-Konvertierung. Falls der Browser HEIC nicht lesen oder konvertieren kann, normalisiert er den MIME-Typ für die serverseitige HEIC/HEIF-Konvertierung. | Gültige HEIC-Dateien in Chromium und WebKit hochgeladen und angezeigt; Backendtests prüfen echte HEIC-Bytes. |
| Fehlender Fokus im „Mehr“-Dialog | Anfangsfokus, Tab-/Shift-Tab-Begrenzung, Fokusrückgabe, Escape und Wiederherstellung der vorherigen Scrollsperre ergänzt. | Browserprüfung für Öffnen, Tab-Zyklus, Escape und Fokusrückgabe. |
| Foto-Upload liest wechselnde IDs | Gemeinsamer Upload-Ablauf erfasst Haushalt, Tier/Pflanze und bisheriges Foto vor dem ersten Await. Wechsel verhindern eine spätere Zuordnung; Aufräumen verwendet immer den ursprünglichen Haushalt. Erfolgreich zugeordnete Dateien werden erhalten. | Tests für Wechsel während Vorverarbeitung, Upload und PATCH sowie für fehlgeschlagene Zuordnung. |
| Verspätetes geschütztes Foto | Anfrageversion und Unmount-Guard verhindern veraltete Ergebnisse. Nicht verwendete Blob-URLs werden sofort freigegeben. | Tests mit vertauschter Antwortreihenfolge, gelöschtem Bild und Antwort nach Unmount. |
| Pflegeaufgaben nach Wechsel | Request-Versionen und Store-Generation verhindern alte Antworten nach Reset oder Wechsel. Kontext-IDs werden zurückgesetzt. Rollback stellt nur betroffene Einträge wieder her und bewahrt neue Daten. Auch die entsprechenden Pflanzenabläufe sind abgesichert. | Verzögerte Antworten, Tier-/Pflanzenwechsel und parallele Socket-Ergänzungen getestet. |
| Einladungscode aus altem Haushalt | Einladung und Mitgliederliste übernehmen nur Antworten des aktuellen Kontexts. Codes werden beim Wechsel geleert. Teilen und Kopieren prüfen die Haushaltszuordnung und Gültigkeit. | Browser hält Antworten aus Haushalt A zurück, wechselt zu B und gibt A erst danach frei: Code und Mitglieder bleiben bei B. |
| Zusätzlich beim Release-Review gefunden: Einladung bleibt nach Erneuerung im Ladezustand | Die aktuelle Erneuerung beendet auch den Ladezustand einer inzwischen veralteten Einladungscode-Abfrage. Kontext- und Versionsprüfung bleiben erhalten. | Browser hält den GET zurück, erneuert den Code und gibt den GET danach frei: neuer Code bleibt sichtbar. Erfolg, Fehler und Haushaltswechsel zusätzlich geprüft. |
| Reload während laufender Anfrage verloren | Ein weiterer Reload wird zusammengefasst nachgeholt. Alle Aufrufer warten auf das Nachladen; Fehler im alten Kontext verhindern den neuen Ladeversuch nicht. | Tests für Warteschlange, Fehler und synchronen Throw; Detailseiten beobachten auch Haushaltswechsel. |
| Bildkante wird auf null gerundet | Browser und Server begrenzen verkleinerte Kanten auf mindestens einen Pixel. | Quer-/Hochformat `10000 × 1` beziehungsweise `1 × 10000` getestet. |
| Unverständlicher Verbindungspunkt | „Mehr“ und Einstellungen zeigen den Status mit Text und einer Erklärung. Offline hat Vorrang vor einem noch nicht getrennten Socket. | Browser prüft Offline-Text und roten Punkt. |
| „Haushalt verlassen“ zu prominent | In den unteren Bereich „Konto & Mitgliedschaft“ verschoben und als dezente Aktion dargestellt; Bestätigungsdialog bleibt erhalten. | Mobile Screenshots und responsive Prüfung. |
| Lange Einstellungsseite | „App & Gerät“ mit Sprache, Verbindung und Benachrichtigungen steht oben. Sprunglinks führen zu Haushaltsverwaltung und Zusatzfunktionen. | Deutsch/Englisch bei mehreren Bildschirmbreiten geprüft. |
| Zusätzlich im WebKit-Test gefunden: Beitrittsformular läuft bei 320 Pixeln über | Das Eingabefeld darf innerhalb seiner Flex-Zeile schrumpfen; derselbe Schutz gilt beim Umbenennen. | Einstellungen gezielt bei 320/393/430/1440 Pixeln nachgeprüft. |
| Undo nach Haushaltswechsel | Rücknahme der Fütterung verwendet den Haushalt der ursprünglichen Fütterungen. | Test wechselt vor Undo den aktiven Haushalt und prüft die ursprüngliche API-Zuordnung. |

Die bereits vorhandene Erklärung der Zahl am App-Symbol bleibt sichtbar: Sie zählt heute anstehende Aufgaben und Erinnerungen. Ohne Ansicht der ursprünglichen iPhone-Anzeige lässt sich weiterhin nicht sicher sagen, ob genau diese Zahl gemeint war.

## Validierung

- Frontend: **473 Tests in 33 Dateien bestanden**, inklusive Regressionstests für Antwortreihenfolgen, Kontextwechsel und Bildkonvertierung. Die abschließenden acht Tests prüfen außerdem Upload nach Unmount, fehlgeschlagene Bereinigung, Bildfehler mit Wiederherstellung, Medikamenten-GET mit paralleler Socket-Gabe sowie Pflege-Löschungen bei Kontextwechsel und parallelen Ergänzungen.
- Frontend-Coverage: Statements **77,49 %**, Branches **72,14 %**; konfigurierte Schwellen eingehalten.
- Tatsächliche App-Typprüfung, Sprachschlüsselprüfung und Produktionsbuild bestanden.
- Vollständige Backend-Suite: **837 Tests bestanden**, Coverage **94 %**, lokal unter Python 3.13. Die CI prüft zusätzlich unter Python 3.12.
- Backend `ruff check .` bestanden.
- Chromium: Registrierung, Katzenseite, PNG/HEIC, Foto nach Reload, Medikamentengabe, Dialogfokus, 15 Routen bei 320/393/430/1440 Pixeln, Deutsch/Englisch und helle/dunkle Darstellung geprüft. Keine gefundenen horizontalen Überläufe oder JavaScript-Ausnahmen in diesem Lauf.
- Zusätzlicher Chromium-Test: verspätete Einladungs-/Mitgliederantworten bei Haushaltswechsel sowie Offline-Anzeige bestanden.
- Pflanzenfotos: PNG und HEIC hochgeladen, Foto nach Reload geprüft und Löschung der ersetzten Datei bestätigt.
- WebKit unter Windows: Foto-Upload mit PNG und HEIC, geschützte Bildanzeige, Sitzung nach Reload, Medikamentengabe und Dialogbedienung bestanden. Auch die Navigation innerhalb der App und 15 Routen bei vier Breiten bestanden ohne JavaScript-Ausnahmen. Dies ist kein Test auf dem tatsächlichen iPhone.

Die Browserprüfungen verwendeten eine getrennte lokale SQLite-Datenbank und einen separaten Upload-Ordner. Es wurden keine Produktionsdaten geändert.

## Betrieb und verbleibende Grenzen

Frontend und Backend müssen gemeinsam veröffentlicht werden. Der Backend-Build installiert zusätzlich `pillow-heif==1.8.0`; die Konvertierung nutzt dessen [offiziell dokumentierten Pillow-Plugin-Einstieg](https://pillow-heif.readthedocs.io/en/stable/pillow-plugin.html).
Die vorhandenen Grenzen von 10 MB pro Upload und 25 Megapixeln vor serverseitigem Decode gelten weiterhin. Ein im Browser erfolgreich dekodiertes großes Foto wird vor dem Upload auf maximal 1600 Pixel verkleinert. Ohne Browserdecoder kann eine darüber liegende Originaldatei weiterhin mit einem verständlichen Größen-/Pixel-Fehler abgelehnt werden.

Keine Datenbankmigration erforderlich. Die Prüfungen betreffen den lokalen Reparaturstand; Produktion und das echte iPhone 17 Pro wurden nicht verifiziert. Ein Merge auf `master` ersetzt kein Deployment der gemeinsam benötigten Frontend- und Backend-Versionen.
