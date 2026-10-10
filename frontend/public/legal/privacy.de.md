# Datenschutzerklärung

*Vorlage (Stand {{terms.version}}) – beschreibt, was die App technisch tatsächlich tut. Vor der Veröffentlichung von einer Fachperson prüfen und an den eigenen Betrieb anpassen (insbesondere Hosting-Standort, Auftragsverarbeiter, Aufsichtsbehörde).*

## 1. Verantwortlicher

**{{operator.name}}**
{{operator.address}}
E-Mail: {{operator.email}}

## 2. Welche Daten wir verarbeiten

### Konto

- E-Mail-Adresse, Anzeigename, Passwort (nur als bcrypt-Hash gespeichert)
- Zeitpunkt der Registrierung, der E-Mail-Bestätigung und der Zustimmung zu diesen Bedingungen
- Anmelde-Sitzungen (Refresh-Tokens, gehasht) zur Erkennung von Missbrauch

### Haushaltsdaten

Alles, was du und die anderen Mitglieder deines Haushalts in der App erfassen: Einkaufslisten, Aufgaben, Putzplan, Ausgaben und Ausgleichszahlungen, Budgets, Termine und Abstimmungen, Essensplanung und Rezepte, Haustiere und Pflanzen, Notizen, hochgeladene Dokumente und Fotos sowie NFC/QR-Tags. Diese Daten sind für alle Mitglieder desselben Haushalts sichtbar.

### Technische Daten

- Server-Logs mit IP-Adresse, Zeitpunkt, aufgerufener Adresse und Browser-Kennung (für Betrieb, Fehlersuche und Schutz vor Missbrauch; kurze Aufbewahrung)
- Rate-Limit-Zähler pro IP-Adresse (flüchtig)

## 3. Wofür wir die Daten verwenden

- Bereitstellung der App und Synchronisation zwischen den Geräten deines Haushalts (Vertragserfüllung)
- E-Mails zur Konto-Sicherheit: Bestätigung der Adresse, Passwort zurücksetzen, Hinweis bei Passwort-Änderung (keine Werbung, kein Newsletter)
- Schutz vor Missbrauch und Sicherheit des Dienstes (berechtigtes Interesse)
- Abrechnung kostenpflichtiger Tarife, sofern du einen solchen buchst (Vertragserfüllung, gesetzliche Aufbewahrungspflichten)

## 4. Cookies und lokale Speicherung

Die App verwendet **kein Tracking** und keine Werbe-Cookies. Gesetzt wird ein einziges, technisch notwendiges Cookie (`casa_rt`) für die Anmeldung. Im Browser-Speicher deines Geräts liegen Einstellungen wie Sprache, gewählter Haushalt und zwischengespeicherte Inhalte für die Offline-Nutzung.

## 5. Push-Benachrichtigungen

Nur wenn du sie auf einem Gerät einschaltest. Dafür wird eine Geräte-Adresse beim Push-Dienst deines Browsers bzw. Betriebssystems (z. B. Apple, Google, Mozilla) gespeichert. Die Nachrichten enthalten kurze Erinnerungstexte. Du kannst Push jederzeit in den Einstellungen abschalten.

## 6. KI-Assistent (optional)

Der KI-Assistent (Rezeptvorschläge, Pflanzenpflege) muss von einem Admin des Haushalts ausdrücklich eingeschaltet werden. Erst dann werden die jeweiligen Eingaben (z. B. Zutatenliste, Pflanzenart) an die API von Anthropic PBC (USA) übermittelt. Es werden keine Kontodaten und keine anderen Haushaltsdaten mitgeschickt. Anthropic verwendet API-Eingaben nach eigener Angabe nicht zum Training seiner Modelle.

## 7. Zahlungen (optional)

Kostenpflichtige Tarife werden über Stripe Payments Europe Ltd. (Irland) abgewickelt. Zahlungsdaten (Karte, Bankverbindung) werden ausschliesslich von Stripe verarbeitet; wir erhalten nur den Abo-Status, die Kunden-Nummer und Rechnungsangaben. Es gilt zusätzlich die Datenschutzerklärung von Stripe.

## 8. Weitergabe an Dritte

Ausser den genannten Dienstleistern (Hosting, E-Mail-Versand, Push-Dienste, Anthropic bei eingeschaltetem KI-Assistenten, Stripe bei Zahlungen, optional ein Fehler-Monitoring ohne Personendaten) geben wir keine Daten weiter – es sei denn, wir sind gesetzlich dazu verpflichtet.

## 9. Speicherdauer

- Konto- und Haushaltsdaten: solange dein Konto bzw. der Haushalt besteht
- Nach dem Löschen deines Kontos: deine Kontodaten werden sofort anonymisiert. Ausgaben und Zahlungen, die andere Mitglieder betreffen, bleiben für diese als «Ehemaliges Mitglied» ohne Namensbezug erhalten.
- Beim Löschen des letzten Mitglieds wird der Haushalt mit allen Daten und Dateien gelöscht.
- Server-Logs: höchstens 30 Tage; Rechnungsdaten gemäss gesetzlichen Fristen
- Sicherungskopien werden regelmässig überschrieben.

## 10. Deine Rechte

Du hast das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung, Datenübertragbarkeit und Widerspruch. Konto und Passwort änderst oder löschst du selbst in den Einstellungen. Für alles andere schreibe an {{operator.email}}. Du kannst dich ausserdem bei der zuständigen Datenschutz-Aufsichtsbehörde beschweren.

## 11. Datensicherheit

Übertragung ausschliesslich verschlüsselt (TLS), Passwörter als bcrypt-Hash, Zugriff auf Haushaltsdaten nur für Mitglieder, regelmässige Sicherheits-Updates. Hochgeladene Dateien werden geprüft und sind nur mit Anmeldung abrufbar.

## 12. Änderungen

Wir passen diese Erklärung an, wenn sich die App oder die Rechtslage ändert. Die aktuelle Fassung ist jederzeit in der App unter «Datenschutz» abrufbar.
