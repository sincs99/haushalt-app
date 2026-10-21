# Umsetzung des Sicherheitsaudits vom 21. Oktober 2026

Ausgangspunkt: Commit `e053c715fa26d3d500c0898837ca52a734e33ed8`, externer Auditbericht `security-audit-skill/haushalt-app/run-1/REPORT.md`. Die zehn ursprünglichen Fälle waren quellenbasierte, noch nicht reproduzierte Hypothesen. Dieser Änderungsstand implementiert ihre Schutzmaßnahmen; er ändert den historischen Auditstatus nicht rückwirkend.

## Änderungen

| Bericht | Umsetzung |
| --- | --- |
| NV-01 – Datenreste beim Kontowechsel | Private Stores werden synchron geleert; Ansichten neu gebunden; laufende Datenanfragen erhalten eine Sitzungsgeneration und werden bei Wechsel abgebrochen bzw. ihre Ergebnisse verworfen. Auch optimistische Rücknahmen und Undo-Meldungen bleiben an ihre Herkunft gebunden. |
| NV-02 – Schlüsselrotation | Refresh-Hashes verwenden domänengetrenntes HMAC-SHA256 mit dem JWT-Schlüssel. Kein SHA256-Altfallback. |
| NV-03 – Refresh/Logout-Rennen | Gemeinsame User-Zeilensperre, atomare Rotation ohne versteckte Zwischencommits, Widerruf der gesamten Nachfolgerkette beim Logout. |
| NV-04 – Socket-Beitritt nach Entzug | Mitgliedschaftsgeneration und gemeinsame Sperre zwischen Beitritt und Entfernung verhindern das Einsetzen eines veralteten positiven Ergebnisses. Benachrichtigungsfehler verhindern die Entfernung nicht; der REST-Aufruf wartet auf lokale Entfernung und den Redis-Publikationsversuch. Auch Logout und Tokenablauf trennen Verbindungen trotz fehlgeschlagener Benachrichtigung. |
| NV-05 – Wiederholung unter falschem Konto | Client-Anfragen behalten Sitzungs-/Haushaltsgeneration; ein alter 401-Auftrag wird nach einem Wechsel nicht erneut gesendet. Cookie-Operationen werden im Tab serialisiert, verspätete Zugangsdaten abgewiesen. |
| NV-06 – Dateireste nach Fehlern | Dateinamen-Steuerzeichen werden vor Speicherung abgelehnt. Physische Pfade werden vor dem Metadaten-Flush erfasst; bekannte Flush-/Commit-Fehler räumen neue Dateien auf. Partielle Schreibfehler werden ebenfalls aufgeräumt. |
| NV-07 – Upload-Quote | Haushaltszeile wird vor Quotenprüfung bis Commit gesperrt; parallele Uploads verbrauchen nicht denselben freien Rest. |
| NV-08 – KI-Kontingente | Atomare UTC-Tagesgrenzen für Haushalt, Konto und Server, standardmäßig 50/20/1000. Eindeutige Reservierungen schützen gegen doppelte Erstattung. Unbekannte Provider-Ausgänge bleiben gezählt; automatische SDK-Wiederholung entfällt. |
| NV-09 – Todo-Fremdzuweisung | Create/PATCH prüfen aktuelle Mitgliedschaft des Assignees. Tag-Beschreibung löst auch bei Altbeständen nur Namen aktueller Haushaltsmitglieder auf. |
| NV-10 – Fremdes Rezept in Event-Poll | Event-Polls lehnen Rezeptreferenzen unabhängig von deren Existenz ab. Antwortmodelle unterdrücken solche Altverweise auch bei Socket-Ausgaben. |

Zusätzliche Härtung: getrennte und zeitlich begrenzte Widget-Caches; Cache-Löschung bei erkannten Authentifizierungsfehlern; sichere JavaScript-String-Einbettung; engere Docker-Build-Kontexte; explizite Proxy-IP statt pauschalem Docker-Netzvertrauen; sichere Produktions-Cookies; gemeinsame interne Redirect-Prüfung; Upload-Restore mit Archivprüfung, separater Vorbereitung, SQL-Transaktion und angehaltener Anwendung.

## Validierung

Die integrierte Fassung basiert zusätzlich auf `master` (`dfa8dd7`). Der vollständige Backendlauf erfolgt auf ausdrücklichen Nutzerwunsch in der GitHub-CI, da lokal zusätzliche Abhängigkeiten fehlen und keine installiert werden sollen. Die CI führt auch die neun zusätzlichen PostgreSQL-Paralleltests in einer ausdrücklich angelegten lokalen Wegwerf-Datenbank aus. Die unten genannten älteren Gesamtlauf-Zahlen gelten nur vor dieser Integration.

Regressionstests sind ergänzt, unter anderem für Kontowechsel mit verzögerten Antworten, Cookie-Reihenfolge, Tokenrotation, drei echte PostgreSQL-Auth-Interleavings, Socket-Entzug, Todo/Poll-Scoping, Upload-Flush-/Commit-Fehler, konkurrierende PostgreSQL-Quoten, KI-Gesamtbudgets, wiederholte Erstattungen, Widget-Caches und fehlerhafte Restore-Archive.

Der Nutzer hat gewöhnliche lokale Regressionstests ausdrücklich als Ausnahme von der zusätzlichen OS-Isolation des Audit-Skills freigegeben. Die Prozesse verwenden eine explizite Umgebung mit Dummy-Konfiguration, temporären Daten und gemockten externen Diensten; keine Installation oder echten Provider-Aufrufe.

- Integriertes Frontend: **819 Tests in 61 Testdateien bestanden**. Localeprüfung (1449 Schlüssel), Typecheck, Vite- und PWA-Build erfolgreich. Das abschließende Buildartefakt verwendet Same-Origin für API-Aufrufe.
- Backend vor der Master-Integration: Gesamtlauf `pytest -q`: **882 bestanden, 9 übersprungen**, keine Fehler (288,77 Sekunden). Die abschließende Socket-Testdatei mit drei zusätzlichen Benachrichtigungsfehlerfällen bestand separat mit **23 Tests**. Zwei im ersten Gesamtlauf gefundene Testannahmen wurden isoliert korrigiert: expliziter Automatikmodus beim Produktions-Cookie-Test und einheitliches Fixture-Datum beim Push-Badge-Test. Keine Assertion wurde abgeschwächt.
- Nach der Integration: 13 Restore-Archivtests und neun Restore-Orchestrierungstests mit gemockten Befehlen (`scripts/tests/test_restore_db_sh.py`) bestanden; Ruff, Diff-Prüfung, Compose-YAML-Prüfung auf doppelte Schlüssel sowie PowerShell- und Bash-Syntaxprüfungen erfolgreich. Alembic erzeugt das PostgreSQL-SQL für `mas1a2b3c4d5:b4c5d6e7f8a9` erfolgreich im Offline-Modus; keine Migration wurde gegen eine Datenbank ausgeführt.
- Neun PostgreSQL-Paralleltests benötigen eine ausdrücklich konfigurierte lokale Testdatenbank und werden ohne diese übersprungen. SQLite-Tests ersetzen diese Sperr-/Parallelitätsnachweise nicht. Kein vollständiger Browserlauf, realer Socket.IO-Transporttest oder Docker-/Nginx-Laufzeittest durchgeführt.

## Deployment und verbleibende Betriebsnachweise

- Die Änderungen werden als PR gegen `master` bereitgestellt. Kein Deployment, produktiver Datenbankeingriff oder echter Provider-Aufruf wurde ausgeführt.
- Frontend und Backend gemeinsam aktualisieren. Bestehende Refresh-Sitzungen werden beim ersten HMAC-Deployment ungültig; Nutzer melden sich erneut an.
- Migration `b4c5d6e7f8a9` legt KI-Budget-/Reservierungstabellen an und übernimmt bekannte globale Tagesverbräuche. Vorhandene Kontoverbräuche in `ai_user_usage` bleiben erhalten; der globale Startwert ist pro Tag das Maximum der Haushalts- und Kontosummen.
- `NPM_TRUSTED_PROXY_IP` muss vor dem Produktionsstart auf die feste interne NPM-IP gesetzt werden. Das dedizierte Proxy-Subnetz darf sich nicht mit vorhandenen Netzen überschneiden. Parallele Compose-Projekte benötigen unterschiedliche Subnetze.
- Tatsächliche NPM-Headerbereinigung, Netzbelegung, Provider-Hartlimits und Produktivmigration bleiben durch den Betreiber zu prüfen; sie sind aus dem Quelltext nicht bestätigt.
- Neue Scriptable-Vorlage auf bestehenden Geräten übernehmen. Bereits gespeicherte Offline-Kopien können nicht aus der Ferne gelöscht werden.
- Upload-Dateisystem und Datenbank teilen keine atomare Transaktion. Bei Prozessabsturz oder Verbindungsverlust während eines möglicherweise erfolgreichen COMMIT bleibt ein Abgleich erforderlich; unklare Commit-Ausgänge löschen vorsichtshalber keine möglicherweise gültigen Anhänge.
- Mehrere Worker verwenden die vorhandene Redis-Koordination. Pub/Sub bestätigt nicht die Entfernung auf allen entfernten Workern; Publikationsfehler werden protokolliert. Eine global synchrone Entzugsgarantie wird nicht behauptet.
- Normale Abmeldung ändert nicht die bisher vorgesehene kurze Restlaufzeit bereits ausgestellter Access-JWTs.

Details zum Betrieb und Restore: [deployment.md](../deployment.md), KI-Grenzen: [ai-assistant.md](../ai-assistant.md), Widget: [widget.md](../widget.md).
