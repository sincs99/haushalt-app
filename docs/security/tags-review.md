# 🔒 Security Review — Tags (NFC-Chips / QR-Sticker)

**Datum:** 2026-10-06
**Reviewer:** Security-Review Agent
**Status:** ✅ Umgesetzt — keine offenen kritischen oder hohen Risiken; zwei Restrisiken dokumentiert (T-03, T-09)
**Branch:** `claude/nfc-qr-tags`
**Scope:** Tag-Modell und Token, Scan-Endpunkte (`resolve`/`execute`), Verwaltung, Rate-Limiting, Logs, Frontend-Route `/t/:token`, PWA/nginx

---

## Geprüfte Dateien

| Datei | Bereich |
|---|---|
| `backend/app/models.py` (`Tag`), `backend/migrations/versions/b7c8d9e0f1a2_add_tags.py` | Datenmodell, Token-Spalte (unique) |
| `backend/app/routers/tags.py` | Verwaltung (Admin), Scan-Endpunkte, Prüfreihenfolge, Rate-Limits |
| `backend/app/services/tag_actions.py` | Aktions-Registry, Ziel-Scoping, Wiederverwendung der Modul-Endpunkte |
| `backend/app/core/log_redaction.py`, `backend/app/main.py` | Schwärzen der Tokens in Logs |
| `frontend/src/views/TagScanView.vue`, `frontend/src/utils/tagScan.ts` | Scan-Ablauf, Bestätigung, Navigation |
| `frontend/src/views/TagsView.vue`, `frontend/src/utils/qr.ts`, `frontend/src/composables/useNfcWriter.ts` | Verwaltung, QR-Code, Web NFC |
| `frontend/src/router/index.ts`, `frontend/src/views/LoginView.vue` | Login-Pflicht, `redirect` |
| `frontend/nginx.conf`, `frontend/vite.config.ts` | Access-Log, SPA-Fallback, Service Worker |
| `backend/tests/test_tags.py` | 79 Tests (Stand 2026-10-10) |

---

## Bedrohungsmodell

Ein Tag ist ein Sticker oder Chip an einem Ort, den Besucher, Handwerker oder Mitbewohner sehen und scannen können. Der Token auf dem Tag ist deshalb **kein Geheimnis im engeren Sinn** und darf allein nichts bewirken. Die Sicherheit beruht auf drei Punkten:

1. **Login und Mitgliedschaft:** `resolve` und `execute` verlangen ein gültiges Access-Token (Authorization-Header) und prüfen die Mitgliedschaft im Haushalt des Tags. Ein Fremder mit dem Sticker in der Hand erreicht ohne Konto im Haushalt nichts.
2. **Bestätigung:** Der Scan öffnet nur die Bestätigungsseite. Erst der Tipp auf den grossen Button ruft `execute` auf. Reine Navigations-Tags (`*.open`) ändern nichts.
3. **Harmlose Aktionen:** Die Registry enthält nur Abhaken, Loggen und Navigieren. **Lösch-Aktionen gibt es nicht** (Test `test_registry_has_no_delete_actions`).

Der Token soll trotzdem nicht erratbar sein und nicht in Logs landen, damit niemand Tags anderer Haushalte findet oder aus Log-Dateien und Backups rekonstruiert.

---

## Zusammenfassung

| # | Schweregrad | Finding | Status |
|---|---|---|---|
| T-01 | 🟡 Mittel | `@limiter.limit` auf `/resolve/{token}` zählt pro URL — jeder geratene Token hätte ein eigenes Kontingent | ✅ Behoben (`shared_limit` mit festem Scope) |
| T-02 | 🟢 Gering | Token steht im URL-Pfad → uvicorn-Access-Log, slowapi-Warnung, nginx-Access-Log (Pfad und Referer) | ✅ Behoben (Schwärzung) |
| T-03 | ℹ️ Info | Nginx Proxy Manager (vor dem Container) loggt Pfade ungeschwärzt | 📝 Restrisiko, Empfehlung unten |
| T-04 | ℹ️ Info | 403 (fremder Haushalt) vs. 404 (unbekannt) verrät eingeloggten Nicht-Mitgliedern, dass ein Token existiert | Akzeptiert (Vorgabe; 192 Bit + Rate-Limit) |
| T-05 | ℹ️ Info | Token liegt im Klartext in der DB und ist für alle Mitglieder lesbar | Akzeptiert (QR-Code muss erneut anzeigbar sein) |
| T-06 | 🟢 Gering | `navigate_to` und Login-`redirect` als mögliche Open Redirects | ✅ Abgesichert |
| T-07 | 🟢 Gering | Polymorphe `target_id` ohne Fremdschlüssel → Ziel aus fremdem Haushalt? | ✅ Abgesichert |
| T-08 | 🟢 Gering | CSRF / Drive-by-Ausführung durch blossen Aufruf der URL | ✅ Durch Design ausgeschlossen |
| T-09 | ℹ️ Info | Physischer Austausch eines Stickers gegen eine fremde URL (Phishing) | 📝 Restrisiko, Betriebshinweis |
| T-10 | ℹ️ Info | Rate-Limit pro IP im Prozessspeicher; ein Haushalt hinter NAT teilt sich das Kontingent | Akzeptiert (wie H-13) |

---

## Token

- `secrets.token_urlsafe(24)`: 192 Bit aus dem CSPRNG, 32 Zeichen `[A-Za-z0-9_-]`, URL-sicher ohne Kodierung. Spalte `tags.token` ist `UNIQUE`; bei 192 Bit ist eine Kollision praktisch ausgeschlossen, ein Treffer würde als IntegrityError (500) auffallen statt still einen fremden Tag zu überschreiben.
- Längere Pfadsegmente als 64 Zeichen werden ohne DB-Abfrage mit 404 beantwortet.
- **Token neu erzeugen** (Admin) ersetzt den Token; der alte Chip bzw. QR-Code liefert danach 404 (Test `test_regenerate_token_invalidates_old`). Das ist der Weg, einen verlorenen oder abfotografierten Sticker zu entwerten.

**Erraten:** Bei 30 Versuchen pro Minute und IP auf je einem Endpunkt und 2¹⁹² möglichen Tokens ist ein Treffer ausgeschlossen, auch bei Tausenden Tags.

### T-05 — Klartext in der DB (ℹ️ Akzeptiert)

Anders als Refresh-Tokens (nur SHA-256-Hash) liegt der Tag-Token im Klartext vor, weil die Verwaltung den QR-Code und die URL jederzeit erneut anzeigen muss (Sticker nachdrucken, zweiten Chip beschreiben). Ein Hash würde das verhindern. Wer die Datenbank lesen kann, hat ohnehin alle Haushaltsdaten; der Token gibt ihm nichts zusätzlich, weil die Ausführung Login und Mitgliedschaft verlangt. Liste und Socket-Events (`tag_created/updated`) liefern den Token nur an Mitglieder des Haushalts — dieselben Personen, die den Sticker auch in der Küche abfotografieren können.

---

## Scan-Endpunkte

### Prüfreihenfolge

| Schritt | Ergebnis | Code |
|---|---|---|
| Kein/ungültiges Access-Token | 401 | `INVALID_CREDENTIALS` |
| Token unbekannt oder zu lang | 404 | `TAG_NOT_FOUND` |
| User ist nicht Mitglied des Tag-Haushalts | 403 | `NOT_HOUSEHOLD_MEMBER` |
| Tag deaktiviert | **410** | `TAG_DISABLED` |
| Aktion nicht (mehr) in der Registry | 422 | `TAG_ACTION_INVALID` |
| Ziel gelöscht | 404 | `TAG_TARGET_NOT_FOUND` |
| `execute` auf Navigations-Tag | 422 | `TAG_NOT_EXECUTABLE` |

**Entscheidung deaktiviert → 410 statt 404:** Der Tag existiert und gehört zum Haushalt des Users; 410 („Gone“) erlaubt der Scan-Seite den Hinweis „deaktiviert, ein Admin kann ihn wieder aktivieren“ statt „gibt es nicht“. Die Mitgliedschaft wird **vorher** geprüft — Nicht-Mitglieder bekommen auch für deaktivierte Tags 403 und erfahren nichts über den Zustand (Test `test_foreign_household_403_even_if_disabled`).

### T-04 — Existenz-Orakel 403/404 (ℹ️ Akzeptiert)

Ein eingeloggter Nutzer eines anderen Haushalts kann an 403 vs. 404 erkennen, ob ein Token existiert. Die Vorgabe verlangt 403 für fremde Haushalte, und das Orakel ist wertlos: Ein gefundener Token erlaubt diesem Nutzer weder Lesen noch Ausführen, und Raten scheitert an T-01 und der Token-Länge.

### T-01 — Rate-Limit zählte pro URL (🟡 Mittel, ✅ Behoben)

slowapi verwendet standardmässig `key_style="url"`: Ein mit `@limiter.limit("30/minute")` dekorierter Endpunkt zählt **pro Pfad**. Bei `/api/tags/resolve/{token}` ist jeder geratene Token ein eigener Pfad — das Limit hätte gegen Raten gar nicht gewirkt. Zusätzlich hätte slowapis Warnung „ratelimit … exceeded at endpoint: <Pfad>“ den Token geloggt.

**Fix:** `@limiter.shared_limit("30/minute", scope="tag-resolve")` bzw. `scope="tag-execute"` — ein Kontingent pro IP und Endpunkt, unabhängig vom Token. Test `test_resolve_rate_limit` rät 30 verschiedene Tokens (404) und erwartet beim 31. ein 429.

**Andere Endpunkte:** Die bestehenden Limits (Login, Register, Refresh, Logout, Join, Push) liegen auf festen Pfaden ohne Pfadparameter und sind nicht betroffen. Bei künftigen Limits auf Pfaden mit Parametern muss ebenfalls `shared_limit` verwendet werden; das steht als Kommentar in `routers/tags.py`.

### T-10 — Kontingent pro IP (ℹ️ Akzeptiert)

Wie H-13 im Hardening-Review: In-Memory, pro IP. Ein Haushalt hinter einem NAT teilt sich 30 `resolve` und 30 `execute` pro Minute — weit mehr, als Menschen scannen.

### T-08 — CSRF / Drive-by (✅ Durch Design)

- Das Aufrufen der URL `/t/<token>` lädt nur die SPA; `resolve` ändert nichts (Ausnahme: Nutzungszähler bei Navigations-Tags), `execute` folgt erst nach dem Tipp.
- Beide Endpunkte sind `POST` und verlangen den `Authorization`-Header, keine Cookies → eine fremde Seite kann sie nicht im Namen des Users auslösen (CORS ohne Credentials, H-03).
- Ein präparierter Link auf `/t/<token>` eines Tags im eigenen Haushalt führt höchstens zur Bestätigungsseite.

### T-07 — Ziel-Scoping (✅ Abgesichert)

`target_id` ist polymorph und hat keinen Fremdschlüssel. Jede Aktion lädt ihr Ziel über `load_target(db, tag.household_id, target_id)`, das `household_id` des Ziels gegen den Tag-Haushalt prüft — beim Anlegen, beim Ändern und bei **jedem** Scan. Ein Tag, der (etwa durch einen Bug oder manuelle DB-Änderung) auf ein fremdes Ziel zeigt, liefert 404 und ändert nichts (Test `test_todo_of_other_household_cannot_be_targeted_via_db_manipulation`). Die Mutation selbst läuft über die bestehenden Endpoint-Funktionen (`create_feeding`, `feed_all`, `complete_care_task` (Tier und Pflanze), `water_all`, `complete_assignment`, `update_todo`) mit derselben Mitgliedschaft (`membership`) und denselben Prüfungen wie in der App.

### Zieltyp Pflanze (✅ Abgesichert, Epic 34)

`plant.water` (Ziel: Pflanze, leer = alle fälligen) und `plant.care_task.done` (Ziel: Pflegeaufgabe, Zieltyp `plant_care_task`) folgen dem Muster der Tier-Aktionen und bleiben im Rahmen „Abhaken/Loggen“ — es gibt keine Lösch- oder Änderungs-Aktion.

- **Scoping:** `load_target` prüft `household_id` für Pflanze und Pflegeaufgabe beim Anlegen, Ändern und bei jedem Scan (Tests: Pflanze/Aufgabe aus fremdem Haushalt → 422 beim Anlegen, fremdes Mitglied → 403, gelöschtes Ziel → 404 `TAG_TARGET_NOT_FOUND`, `target_missing` in der Liste).
- **Mutation über die Router-Funktionen:** `complete_care_task` (je Gießaufgabe der Pflanze) und `water_all`; Log-Eintrag, `done_by_user_id` und Socket-Events `plant_care_task_updated`/`plant_care_logged` sind dieselben wie in der App.
- **Keine Gießaufgabe:** `resolve` meldet `can_execute=false` mit `NO_WATER_TASK` (bei „alle“: `NO_PLANTS`/`NOTHING_DUE`); ein direkter `execute` liefert 409 `TAG_NOTHING_TO_DO` und schreibt nichts.
- **Mehrfach-Scan:** Zwei Scans loggen zweimal (anders als `pet.feed` gibt es keinen Slot). Das ist harmlos — die Fälligkeit wird aus dem Intervall ab heute neu gesetzt — und liegt innerhalb des Scan-Rate-Limits (T-01/T-10).
- **Keine neue Angriffsfläche:** Kein neuer Endpunkt, keine Migration; `describe` liest nur `care-status` des eigenen Haushalts (`care_status`-Funktion, gleicher Haushalt wie der Tag).

### Rollen

Anlegen, Ändern (inkl. Neu-Zuordnen), Deaktivieren, Token neu erzeugen und Löschen verlangen `verify_household_admin`; Lesen der Liste und der Ziel-Optionen `verify_household_access`; Ausführen jede Mitgliedschaft. Tests: `test_member_cannot_create`, `test_member_cannot_update_regenerate_or_delete`, `test_cross_household_management_forbidden`, `test_tag_id_of_other_household_is_404`.

---

## Logs

### T-02 — Token in Logs (🟢 Gering, ✅ Behoben)

| Quelle | Vorher | Nachher |
|---|---|---|
| uvicorn-Access-Log | `POST /api/tags/resolve/<token>` | `POST /api/tags/resolve/***` (Filter `TagTokenRedactionFilter` auf `uvicorn.access`, `uvicorn.error`, `slowapi`) |
| slowapi-Warnung bei 429 | Pfad mit Token (T-01) | Scope `tag-resolve`/`tag-execute`, zusätzlich Filter |
| nginx-Access-Log (Frontend-Container) | `/t/<token>`, `/api/tags/…`, `/login?redirect=/t/<token>`, Referer `…/t/<token>` | eigenes `log_format redacted` mit `map` auf `$request_uri` und `$http_referer` → `***` |
| App-Code | — | Router und Registry loggen keine Tokens |

Der Referer-Fall wurde erst im E2E-Test gefunden: Die Login-Seite (`/login?redirect=/t/<token>`) lädt Assets mit diesem Referer. Beide Muster (`/t/…` und `redirect=/t/…`, auch URL-kodiert) sind abgedeckt.

### T-03 — Nginx Proxy Manager (ℹ️ Restrisiko)

NPM terminiert TLS vor dem Frontend-Container und schreibt eigene Access-Logs mit `$request_uri` und Referer; darauf hat dieses Repository keinen Einfluss. Folgen sind begrenzt (T-05: der Token allein bewirkt nichts). **Empfehlung für den Betrieb:** In NPM für den Proxy-Host unter „Advanced“ `access_log off;` setzen oder die Log-Rotation kurz halten; die Logs des Frontend-Containers reichen für die Fehlersuche.

---

## Frontend

### T-06 — Open Redirects (✅ Abgesichert)

- `navigate_to` kommt vom Server (`/shopping` bzw. `/shopping?list=<uuid>`). Das Frontend akzeptiert trotzdem nur Pfade, die mit `/` beginnen und nicht mit `//` oder `/\` (`safeInternalPath`, Tests in `utils/__tests__/tagScan.test.ts`); sonst `/dashboard`.
- Login-`redirect`: `LoginView` übergibt den Wert an `router.push`; vue-router behandelt ihn als App-Pfad, nicht als externe URL. Unverändert gegenüber dem bisherigen Verhalten.

### Bestätigungsseite

Die Seite zeigt Bezeichnung, Ziel, letzte Fütterung bzw. Fälligkeit und — bei mehreren Haushalten — den Haushaltsnamen, damit niemand versehentlich im falschen Haushalt abhakt. Gehört der Tag zu einem anderen eigenen Haushalt, wechselt die App erst beim Navigieren dorthin; der Server hat die Mitgliedschaft geprüft.

### QR-Code und CSP

`qrcode-generator` (MIT, keine Abhängigkeiten, im Bundle, kein CDN) erzeugt ein SVG, das als `data:image/svg+xml`-URL in ein `<img>` geht. Das ist durch `img-src 'self' data: blob:` gedeckt; es entsteht kein Inline-Markup (`v-html`) im DOM. Download als `.svg` über denselben `data:`-Link.

### Web NFC

`NDEFReader.write({ records: [{ recordType: 'url', data: url }] })` nur nach Feature-Detection (Chrome auf Android). Die `Permissions-Policy` der App schränkt `nfc` nicht ein (Default: `self`). Auf anderen Geräten zeigt die Verwaltung einen Hinweis auf NFC-Apps. Das Schreiben passiert ausschliesslich lokal im Browser des Admins; der Server erfährt davon nichts.

### Service Worker

Navigationen auf `/t/<token>` bedient Workbox aus der vorgecachten App-Shell (`navigateFallback: '/index.html'`). Die Antwort hängt nicht vom Pfad ab, der Token landet in keinem Cache-Eintrag. Es gibt kein `runtimeCaching`; die `POST`-Aufrufe an `/api/tags/*` werden nie gecacht. Offline zeigt die Scan-Seite „Keine Verbindung“ mit „Erneut versuchen“.

### T-09 — Ausgetauschte Sticker (ℹ️ Restrisiko)

Jemand mit Zugang zur Wohnung könnte einen QR-Sticker durch einen mit fremder URL ersetzen oder einen ungesperrten NFC-Chip überschreiben. Die App kann das nicht verhindern. **Betriebshinweise (README):** NFC-Chips nach dem Beschreiben mit der NFC-App sperren („Lock tag“, dauerhaft — bei „Token neu erzeugen“ braucht es dann einen neuen Chip); beim Scannen auf die eigene Domain in der Adresszeile bzw. die eigene App achten; die Bestätigungsseite zeigt immer Haushalt-Inhalte, eine fremde Seite nicht.

---

## Verifikation

**Backend:** `backend/tests/test_tags.py`, 79 Tests (Stand 2026-10-10): Token-Format; CRUD und Rollen; Aktion/Zieltyp-Validierung; Ziel aus fremdem Haushalt; resolve/execute für `pet.feed` (einzeln, alle Tiere, doppelt → 409, Slot-Wahl), `pet.care_task.done`, `chore.assignment.done` (aktuelle Periode vor Rückstand, pausiert, nichts fällig), `shopping_list.open` (nur Navigation, execute → 422), `todo.done` (idempotent), `plant.water` (eine Pflanze, nur fällige Gießaufgaben bei „alle“, keine Gießaufgabe → 409, gelöschte Pflanze → `TAG_TARGET_NOT_FOUND`, fremder Haushalt → 403, Pflanze aus fremdem Haushalt beim Anlegen → 422), `plant.care_task.done`; 401/403/404/410/422; Rate-Limit beider Endpunkte über verschiedene Tokens; Schwärzung in Log-Records und in der slowapi-Warnung.

**E2E (wie H-02):** Produktions-Build (`vite build`) mit der echten `nginx.conf` + `security-headers.conf` (`nginx -t` ok) vor einem lokalen Backend (SQLite, Seed-Daten), headless Chromium (Playwright), Locale `de-DE`, Viewport 390×844:

1. `/t/<token>` ohne Login → `/login?redirect=/t/<token>` → Login über das UI → zurück auf `/t/<token>`
2. „Mia füttern?“ → Tipp → „Fütterung eingetragen“; zweiter Scan → „Für diese Mahlzeit ist schon gefüttert.“
3. Einkaufslisten-Tag → ohne Bestätigung direkt auf `/shopping`
4. Todo-Tag → „„Pflanzen giessen“ erledigt?“ → abgehakt
5. Deaktivierter Tag → Hinweis „deaktiviert“; unbekannter Token → „gibt es nicht (mehr)“
6. `/tags`: Liste, Detail mit QR-Code (Bild geladen), NFC-Hinweis (kein Web NFC in headless), Tag anlegen
7. Danach `/household`, `/shopping`, `/pets`, `/todos`, `/dashboard`

Ergebnis: **0 CSP-Violations**; Console-Errors nur die erwarteten Netzwerkantworten 410 und 404 aus Schritt 5. Access-Logs nach dem Lauf: **kein Token** im nginx-Log (379 Zeilen) und im uvicorn-Log (297 Zeilen).

---

## Gesamtbewertung

Der Token ist bewusst nur ein Zeiger: Ausführen verlangt Login, Mitgliedschaft und einen Tipp, und die Aktionen sind auf Abhaken, Loggen und Navigieren beschränkt. Der einzige echte Befund (T-01, Rate-Limit pro URL) wurde vor dem Merge behoben und ist durch einen Test abgesichert. Offen bleiben Betriebsthemen ausserhalb des Codes (T-03 NPM-Logs, T-09 Sticker-Austausch), beide mit Empfehlung.
