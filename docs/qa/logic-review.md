# Logik-Review der Geschäftsregeln (Stand 2026-10-06)

**Branch:** `claude/logic-review` · **Basis:** `master` nach PR #29 (792 Backend-Tests grün, 363 Frontend-Tests grün)

Dieses Review prüft, ob die App das Verhalten zeigt, das sie in `README.md`,
`docs/PROJECT-STATUS.md` (Geschäftsregeln, Abschnitt 8, Epics 31–34) und
`docs/offline-first-phase2.md` verspricht — und was ein Nutzer darüber hinaus erwartet.
Sicherheit war nicht Gegenstand (siehe `docs/security/`).

**Methode:** Pro Modul wurde der Code gegen die dokumentierten Regeln gelesen, für jede
Regel ein konkretes Szenario formuliert und, wo möglich, mit einem Test geprüft. Bestehende
Tests gelten als Spezifikation, wurden aber hinterfragt. Jeder behobene Fehler hat einen
eigenen Commit mit einem Test, der vorher fehlschlägt.

**Bewertung:**

- **Fehler** — die App verhält sich anders als dokumentiert bzw. als ein Nutzer es
  vernünftigerweise erwartet; behoben in diesem Branch, wenn keine Produktentscheidung nötig ist.
- **Unschärfe** — technisch korrekt, aber überraschend, inkonsistent oder nur in Randfällen
  sichtbar; nicht geändert, Vorschlag steht dabei.
- **ok** — Verhalten entspricht Regel und Erwartung.
- **Entscheidung** — zwei vertretbare Verhalten; der Betreiber muss wählen (Liste am Ende).

---

## 0. Übersicht nach Schwere

| ID | Modul | Befund | Schwere | Status |
|---|---|---|---|---|
| L-01 | Finanzen | Monatswechsel für wiederkehrende Rechnungen, Budget, Finanzübersicht und Standard-Datum von Ausgaben/Ausgleich läuft nach Server-Uhr (UTC), nicht nach Haushaltszeit. Zwischen 00:00 und 01:00/02:00 Uhr Schweizer Zeit landet eine Buchung im Vormonat oder wird als „schon gebucht“ abgelehnt | Fehler (falscher Monat, falsches Datum) | ✅ behoben |
| L-02 | Finanzen | Gebuchte Rechnung mit `split_type="custom"` erzeugt eine Ausgabe mit gleichmässigen Anteilen, aber `split_type="custom"`; danach lässt sich der Betrag der Ausgabe nicht mehr ändern (422 `SHARES_EMPTY`) | Fehler (Datensatz widerspricht sich) | ✅ behoben |
| L-03 | Kalender/Abstimmung | `decide` sendet `event_created` nur mit `{id, title}`; ein geöffneter Kalender fügt den Termin ohne Zeiten ein und stürzt beim Rendern ab (`starts_at.substring`) | Fehler (Absturz der Ansicht) | ✅ behoben |
| L-04 | Aufgaben/Dashboard | Todo mit Fälligkeit „heute“ zählt im Dashboard ab 00:00 UTC (02:00 Schweizer Zeit) als überfällig, in der Aufgabenliste nicht | Fehler (falsche Anzeige, widersprüchlich) | ✅ behoben |
| L-05 | Ämtli | Nach dem Austritt eines Mitglieds lässt sich ein Ämtli mit ihm in der Rotation nicht mehr speichern (422 `USERS_NOT_IN_HOUSEHOLD`), weil die UI die Rotation immer mitschickt — selbst Umbenennen scheitert | Fehler (Datensatz nicht mehr bearbeitbar) | ✅ behoben |
| L-06 | Haustiere | Verschieben der Fälligkeit einer Pflegeaufgabe setzt `notified_at` nicht zurück → keine Push-Erinnerung zur neuen Fälligkeit (Pflanzen machen es richtig) | Fehler (Erinnerung geht verloren) | ✅ behoben |
| L-07 | Frontend | Haushaltswechsel setzt Stores für Haustiere, Pflanzen, Notizen, Essen und Aufgaben nicht zurück; offene Ansichten zeigen weiter Daten des alten Haushalts | Fehler (fremde Daten sichtbar bis Neuladen) | ✅ behoben |
| L-08 | Rollen | Automatisch zum Admin beförderte Person sieht ihre neue Rolle erst nach Neuladen (Socket-Event `household_member_left` aktualisiert `/me` nicht) | Fehler (Regel „wird automatisch Admin“ erst nach Reload wirksam) | ✅ behoben |
| L-09 | Ämtli | Schedule-Änderung gibt pro gelöschter Zuweisung einen Rotationsplatz zurück; wurden beim Materialisieren Ex-Mitglieder übersprungen, stimmt die Rückgabe nicht exakt | Unschärfe | offen |
| L-10 | Ämtli | Pausiertes Ämtli: bereits materialisierte offene Zuweisungen bleiben in Dashboard, Aufgabenliste und Putzplan sichtbar; der Tag lehnt ab | Entscheidung | offen |
| L-11 | Haustiere/Pflanzen | Nächste Fälligkeit nach „Erledigt“ rechnet ab heute, nicht ab der alten Fälligkeit; Intervalländerung verschiebt die bestehende Fälligkeit nicht | Entscheidung | offen |
| L-12 | Einkauf/KI | „Fehlende Zutaten“ aus dem Rezept dedupliziert gegen offene Einträge der Standardliste, der KI-Weg nicht (legt Duplikate in der aktiven Liste an) | Unschärfe | offen |
| L-13 | Kalender | `GET /polls` liefert Optionszeiten in UTC, Termine dagegen in Haushaltszeit; UI zeigt die Zeit nicht an | Unschärfe (API-Inkonsistenz) | offen |
| L-14 | Frontend | Reconnect lädt Kern-Stores neu; Kalender, Haustiere, Pflanzen, Notizen, Essen nur, wenn die Ansicht offen ist | Unschärfe | offen |
| L-15 | Haushalt | Entferntes/ausgetretenes Mitglied bleibt als `assigned_to_user_id` auf Todos und Einkaufseinträgen; UI zeigt keinen Namen | Unschärfe | offen |
| L-16 | Ämtli | UI kann in der Rotation nur sortieren, keine Mitglieder hinzufügen/entfernen (neue Mitglieder kommen nie in bestehende Ämtli) | Unschärfe (UX-Branch) | offen |
| L-17 | KI | Tageslimit zählt pro UTC-Tag (dokumentiert, Abschnitt 8) | Entscheidung | offen |
| L-18 | Aufgaben | Todo-Claim auf ein bereits (auch an mich) vergebenes Todo → 409 (Entscheidung E12/B5 im Offline-Konzept: online-only, kein idempotenter Claim) | ok / dokumentiert | — |

---

## 1. Finanzen

| Regel | Szenario | Erwartung | Ist | Bewertung | Vorschlag / Test |
|---|---|---|---|---|---|
| Even-Split: Summe der Anteile = Betrag, Rest-Rappen verteilt | 100 Rp. auf 3 Personen | 34/33/33, Summe 100 | `split_evenly` verteilt `divmod`-Rest auf die ersten Personen in UUID-Reihenfolge | ok | `test_expense_splits.py::test_even_split_with_remainder`. Der Rest-Rappen geht deterministisch, aber nicht an den Zahler — akzeptabel |
| Even-Split: Zahler ist Teilnehmer? | Anna zahlt 60, Teilnehmer nur Ben, Carla | Anna +60, Ben −30, Carla −30 | Zahler muss Mitglied sein, muss nicht Teilnehmer sein | ok | Entspricht „Anna hat für die anderen bezahlt“ |
| Custom-Split: Summe = Betrag, keine Doppelten | Anteile 40+50 bei Betrag 100 | 422 `SHARES_SUM_MISMATCH` | so | ok | Tests vorhanden |
| Anteil 0 Rp. in Custom-Split | Anteil `{user, 0}` | zulässig (Person war dabei, zahlt nichts) | zulässig (`ge=0`) | ok | — |
| Doppelte Teilnehmer | `participant_ids=[A, A]` | 422 | 422 `DUPLICATE_SHARE_USER` | ok | `test_finance_correctness.py` |
| Salden: Vorzeichen | A zahlt 100, Split A/B | A +50, B −50; Vorschlag „B → A 50“ | `saldo = paid − owed + settled_out − settled_in`; positiv = bekommt Geld | ok | `test_expense_balances.py` |
| Ausgleich reduziert Saldo | B zahlt A 50 (Settlement from=B to=A) | beide 0 | so | ok | — |
| Minimierung der Zahlungen | 4 Personen, Kette | ≤ n−1 Transaktionen | Greedy grösster Gläubiger ↔ grösster Schuldner | ok (dokumentiert „Greedy“, nicht optimal) | Optimal wäre NP-schwer; für 2–5 Personen reicht Greedy |
| Ausgaben ohne Zahler (User gelöscht) | `paid_by_user_id` SET NULL | Betrag als `unassigned_rappen` ausgewiesen, Salden summieren nicht auf 0 | so | ok | — |
| Haushalt verlassen mit offenem Saldo | B schuldet 50, verlässt | erlaubt; Schuld bleibt sichtbar; A kann Ausgleich mit Ex-Mitglied erfassen | `assert_settlement_parties`: eine Seite Mitglied, andere im Ledger | ok | `test_finance_correctness.py::test_ex_member_debt_shows_in_suggestions_and_can_be_settled` |
| Alte Ausgabe mit Ex-Mitglied bearbeiten | Umbenennen mit vollem Payload (UI) | geht | `assert_users_allowed` toleriert Personen, die schon auf dem Datensatz stehen | ok | — |
| Betrag ändern bei gespeichertem Even-Split | 100 → 120, keine Teilnehmer im Payload | auf bisherige Teilnehmer verteilen | so | ok | `test_amount_change_keeps_participant_subset` |
| Betrag ändern bei gespeichertem Custom-Split ohne Anteile | PATCH `amount_rappen` allein | 422 (Anteile nötig) | 422 `SHARES_EMPTY` | ok | — |
| **Wiederkehrende Rechnung: idempotent pro Monat** | zweimal buchen im selben Monat | 409 `BILL_ALREADY_BOOKED` | Unique `(recurring_bill_id, booked_month)` + Vorabprüfung | ok | `test_recurring_bill_book.py` |
| **Monatswechsel / Zeitzone** | Haushalt `Europe/Zurich`, Buchung am 1.11. um 00:30 Uhr (= 31.10. 23:30 UTC) | Buchung für **November**, `expense_date` im November | `date.today()` (Server-Uhr = UTC im Container) → `booked_month = 2026-10-01`; war Oktober schon gebucht → 409, sonst eine zweite Oktober-Buchung und November kann erst ab 01:00 Uhr gebucht werden | **Fehler L-01** | **Behoben:** `services/household_time.household_today()`; Rechnungen, Budget (Default-Monat), Finanzübersicht (Default-Monat, `days_elapsed`), Standard-`expense_date`/`settled_date` und Standardwoche des Menüplans rechnen in Haushaltszeit. Test `test_household_time.py` (Buchung um 23:30 UTC am 31.10. → `booked_month` 1.11.) |
| Standard-Zahler | Rechnung ohne Zahler buchen | 422 `BILL_PAYER_REQUIRED` | so; Request-Zahler hat Vorrang | ok | — |
| **Rechnung mit `split_type="custom"`** | API: Bill `custom` buchen, danach Betrag der Ausgabe ändern | Ausgabe konsistent, Betrag änderbar | Anteile werden gleichmässig berechnet (es gibt kein Anteilsmodell für Rechnungen), die Ausgabe trägt aber `split_type="custom"` → PATCH `amount_rappen` scheitert mit 422 `SHARES_EMPTY`; Frontend zeigt „Individuell“ | **Fehler L-02** | **Behoben:** gebuchte Ausgabe trägt `split_type="even"` (das ist, was gebucht wurde). `RecurringBill.split_type` bleibt als Feld bestehen, hat aber keine Wirkung → Entscheidung E-5 |
| Budget pro Monat: Monatsgrenze | Ausgabe `expense_date` 31.10., Budget Oktober | zählt zu Oktober | `expense_date >= month AND < first_of_next_month` | ok | — |
| Budget: Default-Monat | `GET /budget` ohne `month` um 00:30 Uhr am 1.11. | November | UTC-Datum → Oktober | **Fehler L-01** | behoben (siehe oben) |
| Währungsregel | Ausgabe mit `EUR` in CHF-Haushalt | 422 `CURRENCY_MISMATCH` | so; gespeichert wird immer die Haushaltswährung | ok | `test_currency.py` |
| Löschen einer Rechnung | Rechnung mit gebuchten Ausgaben löschen | Ausgaben bleiben (`recurring_bill_id` SET NULL) | so (`ondelete=SET NULL`) | ok | — |
| Mitglied entfernen mit Saldo | Admin entfernt B mit −50 | erlaubt, Saldo bleibt sichtbar | so | ok | `test_leave_remove.py::test_balances_show_ex_member` |

## 2. Ämtli-Rotation

| Regel | Szenario | Erwartung | Ist | Bewertung | Vorschlag / Test |
|---|---|---|---|---|---|
| Materialisierung lazy, 7 Tage voraus, 14 Tage zurück | GET assignments | Zuweisungen bis heute+7, Backfill max. 14 Tage | so, Savepoint gegen parallele Requests | ok | `test_chores.py` |
| Rotation [A,B,C], C tritt aus | nächste Zuweisungen | A, B, A, B … | Scheduler überspringt Nicht-Mitglieder, Index rückt weiter | ok | `test_rotation_skips_departed_member` |
| Alle in Rotation ausgetreten | Materialisierung | Zuweisung ohne Person (`assigned_user_id=None`) | so | ok | — |
| **Ämtli bearbeiten nach Austritt** | C ist in der Rotation, tritt aus; A benennt das Ämtli um (UI schickt `rotation_order` immer mit) | speichern geht | `_validate_rotation_order` verlangt, dass alle in der Rotation Mitglieder sind → 422; die UI kann Personen nur umsortieren, nicht entfernen → **Ämtli nicht mehr bearbeitbar** | **Fehler L-05** | **Behoben:** Beim PATCH dürfen Personen, die schon in der gespeicherten Rotation stehen, Ex-Mitglieder sein (gleiches Muster wie `assert_users_allowed` bei Ausgaben); neu hinzukommende müssen Mitglieder sein. Test `test_rename_chore_with_departed_member_in_rotation`. UI-Erweiterung (Mitglieder hinzufügen/entfernen) → L-16, UX-Branch |
| Schedule-Änderung löscht zukünftige Zuweisungen | weekly Mo → monthly 15.; 08-10 offen, 08-03 erledigt | 08-03 bleibt, 08-10 weg; Rotationsplatz zurück | so; `next_rotation_index -= deleted` | ok | `test_patch_recurrence_deletes_future_assignments`, `test_real_schedule_change_continues_rotation` |
| Erledigte zukünftige Zuweisung bei Schedule-Änderung | Zuweisung in 3 Tagen vorzeitig erledigt, dann Wochentag geändert | erledigte bleibt erhalten | nur `completed_at IS NULL` wird gelöscht | ok (kein Verlust) | Die erledigte Zuweisung blockiert als `last_assignment` die Neuplanung bis zu ihrem Datum — Unschärfe, selten |
| Rotationsrückgabe bei übersprungenen Ex-Mitgliedern | Rotation [A,C(ex),B]; 2 Zuweisungen gelöscht, die je 1–2 Index-Schritte gekostet haben | gleiche Person wie vor der Änderung ist als Nächste dran | Rückgabe zählt Zuweisungen, nicht Index-Schritte → kann um eine Position verrutschen | Unschärfe L-09 | Rotation bereinigen oder Index-Schritte pro Zuweisung speichern; geringe Auswirkung |
| Umbenennen mit vollem Payload setzt Zeitplan nicht neu | UI-Payload mit unveränderten Feldern | Zuweisungen bleiben | nur echte Wertänderungen zählen | ok | `test_rename_with_full_payload_keeps_assignments` |
| biweekly / monthly an Monatsenden | 31. in Februar/Schaltjahr | geclampt auf Monatsende | so | ok | `test_monthly_day31_february`, `_leap_year` |
| biweekly-Parität nach Schedule-Wechsel | weekly → biweekly | `anchor_date` = erster neuer Termin, Parität ab dort | `_compute_anchor_date` bei Änderung | ok | `test_biweekly_rename_keeps_week_parity` |
| Abhaken/Rückgängig idempotent | zweimal `complete` | 200, keine Änderung | so; `completed_by` = wer zuletzt erledigt hat | ok | — |
| Reassign | an Nicht-Mitglied | 422 | so | ok | — |
| Pausiertes Ämtli | `active=false`, Zuweisungen in den nächsten 7 Tagen schon materialisiert | ? | Zuweisungen bleiben in `GET /assignments`, `/tasks` und Dashboard sichtbar; keine neuen werden erzeugt; `chore.assignment.done`-Tag lehnt ab (`CHORE_INACTIVE`) | Entscheidung L-10 | Entweder offene Zuweisungen beim Pausieren ausblenden (Filter `Chore.active`) oder löschen |
| Rotation ändern | [A,B] → [A,B,C] | ab wann gilt C? | bestehende Zuweisungen bleiben; `next_rotation_index` wird nicht angepasst (Index 5 % 3 = 2 → C) | Unschärfe | akzeptabel; dokumentieren |
| Ämtli löschen | mit erledigten Zuweisungen | Zuweisungen weg (dokumentiert) | CASCADE | ok (dokumentiert) | Statistik wäre damit weg → Chores-Statistiken sind ohnehin offen |

## 3. Kalender

| Regel | Szenario | Erwartung | Ist | Bewertung | Vorschlag / Test |
|---|---|---|---|---|---|
| Wanduhrzeit in Haushaltszeit, UTC gespeichert | 09:00 ohne Offset senden | 09:00 für alle, `+02:00` in der Antwort | `to_utc` / `to_household_time` | ok | `test_event_times.py` |
| Sommerzeit-Wechsel | 09:00 am 25.10. (Winterzeit) | `+01:00` | ZoneInfo | ok | `test_winter_time_offset` |
| Termin über Mitternacht | 23:00–01:00 | an beiden Tagen sichtbar | Bereichsabfrage `starts_at < end AND coalesce(ends_at, starts_at) >= start`; UI expandiert auf Tage | ok | `test_multi_day_event_starting_before_range` |
| Zeitraum-Abfrage an Tagesgrenzen | `to_date` als Datum | ganzer letzter Tag inklusive | `range_bounds` nimmt Folgetag 00:00 als Ende | ok | `test_week_range_includes_sunday` |
| Termin endet exakt um 00:00 des Folgetags | 22:00–00:00 | nur am Starttag | erscheint auch am Folgetag (`>= start`) | Unschärfe | `>` statt `>=` für `ends_at`, aber `>=` für `starts_at` nötig (ganztägig) — kosmetisch |
| Ganztägig | `all_day=true`, 00:00 bis 23:59 lokal | Datum bleibt über DST stabil | so | ok | `test_all_day_event_keeps_its_date` |
| Dashboard „heute“ | Termin 00:30 lokal | heute | Grenzen in Haushaltszeit | ok | `test_dashboard_today_events_in_household_time`. Mehrtägige Termine, die heute nur hineinreichen, fehlen — Unschärfe |
| **Abstimmung → Termin (`decide`)** | Kalender geöffnet, jemand entscheidet eine Abstimmung | Termin erscheint mit Zeit | Server sendet `event_created` mit `{id, title}`; `handleEventCreated` fügt das Objekt ein; `expandEventToDays(e.starts_at)` → `TypeError: Cannot read properties of undefined (reading 'substring')` → Ansicht bricht ab | **Fehler L-03** | **Behoben:** `decide` emittiert die vollständige `EventResponse` in Haushaltszeit (wie `POST /events`). Test `test_decide_emits_full_event_payload` |
| Optionszeiten der Abstimmung | Option 19:00 ohne Offset | als Haushaltszeit gelesen, Termin bei `decide` um 19:00 lokal | `to_utc` beim Anlegen, Rückkonversion bei `decide` | ok | `PollOptionResponse.starts_at` wird in UTC geliefert (nicht konvertiert) — die UI zeigt sie nicht an → Unschärfe L-13 |
| Zwei gleichzeitige `decide` | | genau ein Termin | bedingtes UPDATE `status='offen'` | ok | — |
| Löschen eines Kalenders mit Terminen | | abgelehnt | 422 `CALENDAR_NOT_EMPTY`; letzter Kalender 422 `LAST_CALENDAR` | ok | Dokumentiert in Epic 20 |
| Teilnehmer | Nicht-Mitglied als Teilnehmer | ? | nicht validiert; UI bietet nur Mitglieder | Unschärfe | Validierung analog Ausgaben wäre günstig |

## 4. Haustiere und Pflanzen

| Regel | Szenario | Erwartung | Ist | Bewertung | Vorschlag / Test |
|---|---|---|---|---|---|
| Fütterungs-Slots pro Tag in Haushaltszeit | Fütterung 00:30 lokal | zählt zum neuen Tag | `date` = Haushaltsdatum; Unique `(pet, date, slot)` | ok | — |
| Zweite Fütterung gleicher Slot | | 409 `FEEDING_DUPLICATE` | so | ok | — |
| `feed-all` Idempotenz | zweimal | zweites Mal leer | bereits gefütterte übersprungen; Race → `[]` | ok | — |
| Tag `pet.feed`: Slot ab 14 Uhr Abend | Scan 15:00 lokal | evening | `default_feeding_slot` nach Haushaltsstunde, auf der Bestätigungsseite umschaltbar | ok | — |
| Pflegeaufgabe erledigen → `next_due` | Intervall 30, fällig 1.10., erledigt 5.10. | ? | `today + interval` = 4.11. (ab heute) | Entscheidung L-11 | Alternativ ab Fälligkeit (31.10.). Beide Module verhalten sich gleich, dokumentiert in Epic 31 („aus dem Intervall“) |
| Überfällig vs. heute | `next_due_at == today` | heute, nicht überfällig | Pflanzen: `due_today` / `overdue` getrennt; Tiere im Dashboard: `is_overdue = next_due < today` | ok | — |
| `water-all` Idempotenz | zweimal | zweites Mal leer | nur `next_due_at <= today`; nach Erledigung in der Zukunft | ok | `test_water_all_only_due_water_tasks` |
| Mehrfach-Scan `plant.water` mit Ziel | zweimal | ? | loggt zweimal, `next_due` erneut ab heute (dokumentiert in Epic 34) | Unschärfe (dokumentiert) | wie `todo.done`: zweiter Scan am selben Tag als `changed=false` |
| Push einmalig pro Fälligkeit | fällig, 8:00 lokal | eine Push, `notified_at` gesetzt | bedingtes UPDATE | ok | `test_push.py` |
| `notified_at`-Reset bei Erledigung | | zurückgesetzt | beide Module | ok | `test_complete_resets_notified_at` |
| **`notified_at`-Reset beim Verschieben der Fälligkeit (Tiere)** | Wurmkur heute fällig, Push verschickt; Fälligkeit per PATCH auf +7 Tage | in 7 Tagen erneut Push | Pflanzen: `next_due_at` im PATCH → `notified_at = None`. Tiere: kein Reset → **nie wieder eine Erinnerung**, bis einmal „erledigt“ gedrückt wird | **Fehler L-06** | **Behoben:** `update_care_task` (Tiere) setzt `notified_at` bei `next_due_at` zurück. Test `test_update_care_task_due_date_resets_notified_at` |
| `notified_at` bei Intervalländerung | Intervall 30 → 60, Fälligkeit unverändert | ? | Fälligkeit bleibt (Intervall wirkt ab nächstem Erledigen), `notified_at` bleibt | Entscheidung L-11 | ok, solange die Fälligkeit nicht verschoben wird |
| Foto: eine Datei gehört höchstens einem Tier/einer Pflanze/einem Dokument | Tierfoto an Pflanze hängen | 422 `FILE_IN_USE` | `file_in_use` prüft Pet, Plant, Document | ok | `test_photo_cannot_use_pet_photo` |
| Tier/Pflanze löschen entfernt eigenes Foto | | Datei weg, fremd referenzierte bleibt | so | ok | — |

## 5. Einkauf

| Regel | Szenario | Erwartung | Ist | Bewertung | Vorschlag / Test |
|---|---|---|---|---|---|
| Mehrere Listen, aktive Liste pro Haushalt in localStorage | Liste gelöscht | erste verbleibende wird aktiv | so (REST und Socket) | ok | — |
| Geschäfts-Normalisierung | „coop“, „Coop “, „COOP“ | eine Gruppe, häufigste Schreibweise | `canonical_stores` | ok | `test_shopping_stores.py` |
| Einziges Item eines Stores umschreiben | „coop“ → „Coop“ | neue Schreibweise gewinnt | `exclude_item_id` | ok | — |
| Abgehakte Einträge | GET ohne `include_checked` | nur offene | so | ok | E8 (Wachstum) offen, dokumentiert |
| „Fehlende Zutaten“ aus Rezept | Zutat schon offen auf der Liste | übersprungen (`skipped`) | case-insensitiv gegen offene Einträge der **ersten** Liste | ok | Zutaten mit Menge im Text („200 g Mehl“) werden als Name übernommen — Unschärfe, Datenmodell der Rezepte |
| „Fehlende Zutaten“ aus KI-Vorschlag | Zutat schon offen | ? | `aiStore.addMissingToShopping` legt jeden Eintrag in der **aktiven** Liste an, ohne Duplikatprüfung | Unschärfe L-12 | Backend-Endpunkt mit Dedupe nutzen oder Client-seitig gegen `activeListItems` prüfen |
| Client-IDs idempotent | gleicher Create zweimal | 200 mit bestehendem Objekt, kein zweites Event | `get_existing_by_client_id` + `commit_or_get_existing` | ok | `test_offline_sync.py` |
| Client-ID aus fremdem Haushalt | | 409 ohne Details | so | ok | — |
| Versionierte Merges | Socket-Event älter als REST-Antwort | verworfen | `upsertVersioned` | ok | `syncRaces.test.ts` |
| Gleichzeitige Bearbeitung zweier Felder | A ändert Name, B Menge | beide bleiben (LWW pro Feld) | PATCH nur mit gesendeten Feldern | ok | dokumentiert E2 |
| Löschen vs. Bearbeiten | A löscht, B bearbeitet | Löschen gewinnt, 404 | so | ok | E3 |

## 6. Aufgaben

| Regel | Szenario | Erwartung | Ist | Bewertung | Vorschlag / Test |
|---|---|---|---|---|---|
| Fälligkeit eines Todos ist ein Datum | UI sendet `2026-10-08` | gilt den ganzen 8.10. | gespeichert als `2026-10-08T00:00:00Z` (`DateTime`) | ok (Darstellung in CH korrekt) | Für Geräte westlich von UTC würde der Vortag angezeigt — Unschärfe, Spalte wäre als `Date` sauberer |
| **Überfällig im Dashboard** | Todo fällig heute, Abruf 10:00 Uhr | nicht überfällig (Aufgabenliste: `isOverdue` vergleicht mit lokaler Mitternacht) | Dashboard: `due_date < now()` → ab 02:00 Uhr Schweizer Zeit überfällig, Badge „1 überfällig“, Eintrag rot und an erster Stelle | **Fehler L-04** | **Behoben:** Dashboard vergleicht mit Tagesbeginn in Haushaltszeit (`due_date < today_start`). Test `test_dashboard_todo_due_today_is_not_overdue` |
| Unified Tasks: Sortierung an Tagesgrenzen | Todo `2026-10-08`, Ämtli 08.10. | gleicher Tag | `due_date.date()` von `00:00Z` → 08.10.; NULLS LAST | ok | — |
| Claim | zwei Personen gleichzeitig | genau eine gewinnt, andere 409 | bedingtes UPDATE | ok | `test_todo_claim.py` |
| Claim auf eigenes Todo | schon mir zugewiesen | ? | 409 `TODO_ALREADY_CLAIMED` | ok (E12: online-only, B5 nicht umgesetzt) | — |
| Erinnerungen: max 5, in der Zukunft, einmalig | | | so; erledigtes Todo markiert offene Erinnerungen als `notified` | ok | `test_todo_reminders.py`, `test_push.py` |
| Erinnerung, Backend lange offline | 13 h überfällig | nicht nachträglich senden | `STALE_AFTER` 12 h | ok | — |
| Todo wieder öffnen | nach Erledigung | Erinnerungen bleiben „verschickt“ | so (Zeitpunkt ist eh vorbei) | ok | — |
| Tags | Leerzeichen, Länge 1–50, max 20 | | validiert | ok | `test_todo_tags.py` |
| Ex-Mitglied als Zuständiger | B tritt aus, Todo bleibt B zugewiesen | ? | bleibt; UI findet keinen Namen; Push an „Zugewiesenen“ fällt auf alle Mitglieder zurück | Unschärfe L-15 | beim Austritt `assigned_to_user_id` auf NULL setzen (Produktentscheidung, siehe E-6) |

## 7. Haushalt und Rollen

| Regel | Szenario | Erwartung | Ist | Bewertung | Vorschlag / Test |
|---|---|---|---|---|---|
| Letzter Admin verlässt | A (Admin) geht, B, C bleiben | dienstältestes Mitglied wird Admin | `sorted(joined_at, user_id)[0]` | ok | `test_leave_admin_auto_promote` |
| **Beförderung sichtbar?** | B wird befördert, hat die App offen | B sieht Admin-Funktionen | Socket-Event `household_member_left` → `_handleRemoval` nur für die eigene Person; `households[].role` bleibt `member` bis Neuladen; Admin-Buttons (Umbenennen, Entfernen, Tags, KI) fehlen | **Fehler L-08** | **Behoben:** `handleMemberLeft`/`handleMemberRemoved` für andere Personen laden `/me` neu (Rolle, Haushaltsliste). Test `auth.test.ts` |
| Einziges Mitglied verlässt | | Haushalt gelöscht inkl. Dateien | CASCADE + `delete_household` | ok | `test_leave_last_member_deletes_household`, `test_last_member_leaving_deletes_household_files` |
| Admin entfernt sich selbst | | 422 `CANNOT_REMOVE_SELF` | so | ok | — |
| Admin entfernt Admin | | 403 | so | ok | — |
| Einladungscode läuft nach 7 Tagen ab, Rotation bei Entfernen/Admin-Button | Entferntes Mitglied nutzt alten Code | 404 (Code existiert nicht mehr) | so | ok | `test_removed_member_cannot_rejoin_with_old_code` |
| Abgelaufener Code | | 410 `INVITE_CODE_EXPIRED` | Join und Register | ok | `test_household_join.py`, `test_register.py` |
| Registrierung: genau eines von Name/Code | | 422 | Validator | ok | — |
| 0-Haushalte-Guard | User ohne Haushalt | `/no-household` | Router-Guard (nur wenn `/me` geladen) | ok | — |
| Nach Verlassen des einzigen Haushalts | | Zustand „kein Haushalt“ | Socket-Event `household_member_left` → `_handleRemoval`; ohne Socket: `fetchMe()` lässt `currentHouseholdId` stehen, Guard leitet trotzdem um | ok | — |
| **Haushaltswechsel im Frontend** | Zwei Haushalte; Nutzer ist auf „Haustiere“ und wechselt | Haustiere des neuen Haushalts | `App.vue` leert Einkauf/Todos/Finanzen/Ämtli/Dashboard/Abstimmungen und lädt neu; **Haustiere, Pflanzen, Notizen, Essen, Aufgaben (Unified) bleiben gefüllt** und die Ansichten laden nicht neu (kein Watch) → Daten des alten Haushalts bleiben sichtbar, Aktionen gehen gegen den neuen Haushalt | **Fehler L-07** | **Behoben:** zentrale `resetHouseholdScopedStores()` (leert auch Kalender, Haustiere, Pflanzen, Notizen, Essen, Aufgaben), Ansichten Haustiere/Pflanzen/Notizen/Essen laden bei Wechsel neu. Test `householdScope.test.ts` |
| Socket-Räume beim Wechsel | | alten Raum verlassen, neuen betreten | `leaveHousehold(old)` + `joinHousehold(new)` | ok | — |
| Entferntes Mitglied verliert Echtzeit-Daten | | aus Raum geworfen | `evict_user_id` | ok | `test_member_lifecycle.py` |

## 8. Dokumente und Uploads

| Regel | Szenario | Erwartung | Ist | Bewertung | Vorschlag / Test |
|---|---|---|---|---|---|
| Ablaufdaten | `expiry_date` setzen | gespeichert, Anzeige | so; keine Erinnerung (dokumentiert offen) | ok | — |
| Speicher-Quota | Upload, der die Quota sprengt | 422 `STORAGE_QUOTA_EXCEEDED` | geprüft gegen die **verarbeitete** Grösse (Bilder verkleinert) | ok | — |
| Quota beim „Ersetzen“ | Seite ersetzen = neue hochladen, dann alte löschen | ? | es gibt kein Ersetzen; zwischenzeitlich zählen beide Dateien → an der Quota-Grenze scheitert der Upload | Unschärfe | Hinweis in der UI oder Reihenfolge „erst löschen“ |
| Orphan-Cleanup vs. laufender Upload | mehrseitiger Upload dauert | nicht gelöscht | Frist 24 h | ok | `test_orphan_cleanup_keeps_plant_photo` |
| `file_in_use` über alle Referenzen | Datei an Tier, Pflanze oder Dokument | 422 beim Löschen/Umhängen | alle drei geprüft | ok | `test_file_references.py` |
| Dokument löschen | | alle Seiten + Dateien weg | so | ok | — |
| Letzte Seite entfernen | | 422 `DOCUMENT_LAST_FILE` | so | ok | — |
| Multipart-Upload teilweise fehlgeschlagen | Datei 2 ungültig | nichts gespeichert | Rollback + Storage-Cleanup | ok | — |

## 9. Tags

| Regel | Szenario | Erwartung | Ist | Bewertung | Vorschlag / Test |
|---|---|---|---|---|---|
| Ziel gelöscht | Tag auf gelöschtes Todo | 404 `TAG_TARGET_NOT_FOUND`; Verwaltung zeigt `target_missing` | so | ok | `test_tags.py` |
| Tag deaktiviert | | 410 `TAG_DISABLED`, aber 403 für Fremde zuerst | Prüfreihenfolge dokumentiert | ok | — |
| Mehrfachausführung `todo.done` | zweimal | zweites Mal `changed=false` | so | ok | — |
| Mehrfachausführung `pet.feed` (ein Tier) | zweimal | Hinweis statt Fehler | `resolve` liefert `ALREADY_FED` (Button weg); `execute` würde 409 `FEEDING_DUPLICATE` liefern | ok | — |
| Mehrfachausführung `plant.water` (ein Ziel) | zweimal | ? | loggt zweimal (dokumentiert) | Unschärfe | siehe Abschnitt 4 |
| `chore.assignment.done` | offene Zuweisung heute oder bis 6 Tage voraus | diese wird erledigt, ältere offene bleiben | so | ok | — |
| Zähler | `use_count`, `last_used_at` | nur bei Ausführung bzw. Navigation | `_record_use` nach Erfolg | ok | — |
| Admin-Regeln | Anlegen/Ändern/Löschen/Token | Admin; Ausführen alle | `verify_household_admin` | ok | — |
| Neu zuordnen | `target_type` ändern ohne `action` | Kombination validiert | `_validate_definition` | ok | — |
| Max 200 Tags | | 422 | so | ok | — |

## 10. KI-Assistent

| Regel | Szenario | Erwartung | Ist | Bewertung | Vorschlag / Test |
|---|---|---|---|---|---|
| Tageslimit-Reservierung bei Fehlschlag | Netzwerkfehler / Überlast | Zähler zurückgegeben | `release_call` für `AiNotConfigured`, `AiBusy`, `AiUnavailable` | ok | `test_sdk_errors_are_mapped_and_not_counted` |
| Ablehnung / unbrauchbare Antwort | `refusal`, `max_tokens` | gezählt (Kosten entstanden) | gezählt, Tokens verbucht | ok | A-02: Schemafehler ohne Token-Zahlen gezählt, aber ohne Tokens — dokumentiert |
| UTC-Tag vs. Haushaltszeit | 00:30 Uhr Schweizer Zeit | ? | Zähler wechselt um 01:00/02:00 Uhr | Entscheidung L-17 (dokumentiert Abschnitt 8) | — |
| Opt-in-Wechsel während laufender Anfrage | Admin schaltet aus | laufende Anfrage endet normal, nächste 403 | Prüfung nur zu Beginn | ok | — |
| Rezept speichern mit fehlenden Feldern | Modell liefert kein `duration_min`, `cost_rappen` | speicherbar | `RecipeCreate` mit Defaults; Ausgabe wird in Grenzen geschnitten | ok | `test_recipe_suggestion_can_be_saved_via_recipe_endpoint` |
| Pflanzen-Hinweise übernehmen | Aufgaben existieren bereits | aktualisieren statt duplizieren | `applyAdviceTasks` liest frisch, bricht bei Fehler ab | ok | `plants.test.ts` |
| Limit pro Haushalt über weitere Haushalte | | — | A-01 offen (dokumentiert) | Entscheidung | — |

## 11. Auth und Sitzung

| Regel | Szenario | Erwartung | Ist | Bewertung | Vorschlag / Test |
|---|---|---|---|---|---|
| Refresh-Rotation mit Grace-Window | zwei Tabs refreshen gleichzeitig | beide bekommen gültige Tokens | 30 s Grace, Replacement wird weiterrotiert | ok | `test_auth_refresh.py` |
| Reuse-Erkennung | alter Token nach Grace | alle Tokens des Users widerrufen, Sockets getrennt | so (`revoked`) | ok | — |
| Logout | | Token widerrufen, Cookie gelöscht, Sockets getrennt | alle Verbindungen des Users (dokumentiert, Abschnitt 8) | ok | — |
| „Überall abmelden“ | | — | nicht vorhanden (dokumentiert offen) | — | — |
| Cross-Tab | Logout in Tab A | Tab B meldet sich ab | Storage-Marker | ok | `auth.test.ts` |
| Migration alter Tokens | `haushalt_tokens` im localStorage | einmalig gegen Cookie getauscht | `takeLegacyRefreshToken` | ok | — |
| Zeitzonen in Tokens | `exp` | UTC-aware | `datetime.now(timezone.utc)`; SQLite-naive Werte werden als UTC gelesen | ok | — |
| Socket nach Token-Ablauf | | `session_ended: expired` → Refresh → Reconnect; höchstens ein Refresh pro Verlust | so | ok | `test_socket_session.py` |

## 12. Frontend-Stores

| Regel | Szenario | Erwartung | Ist | Bewertung | Vorschlag / Test |
|---|---|---|---|---|---|
| Optimistische Updates mit Rollback | Server 500 beim Abhaken | Zustand zurück | Snapshot/Rollback in Shopping, Todos, Chores, Kalender, Notizen, Dokumente | ok | Store-Tests |
| Race REST-Antwort vs. Socket-Event | Socket schneller | kein Duplikat, keine veraltete Version | Client-IDs + `upsertVersioned` | ok | `syncRaces.test.ts` |
| Rollback-Position nach parallelem Löschen | | kosmetisch | dokumentiert | ok | — |
| Reconnect-Nachladen | Verbindung zurück | Kern-Stores neu laden | `handleReconnect` in `App.vue`; Kalender/Haustiere/Pflanzen/Notizen/Essen nur, wenn ihre Ansicht offen ist | Unschärfe L-14 | reicht, weil diese Ansichten beim Öffnen laden; Detailansichten (Tier/Pflanze) laden ebenfalls bei Reconnect |
| Haushaltswechsel | | siehe Abschnitt 7 | **Fehler L-07**, behoben | | |
| Offline-Marker | kein Netz beim Start | Shell „offline eingeloggt“ | `hasOfflineSession` | ok | dokumentiert Abschnitt 8 |

---

## Korrigierte Tests

Keine bestehenden Tests mussten geändert werden; alle Fehler liessen sich mit zusätzlichen
Tests nachweisen. Wo neue Tests „heute“ brauchen, wird `household_today`/`_utc_now` in
`app/services/household_time.py` gepatcht (so wie `today_in_tz` in den Ämtli-Tests).

## Offene Produktentscheidungen für den Betreiber

| # | Frage | Optionen | Betroffen |
|---|---|---|---|
| E-1 | Nächste Fälligkeit nach „Erledigt“ bei Tier-/Pflanzenpflege: ab heute oder ab alter Fälligkeit? | a) ab heute (heute) · b) ab Fälligkeit (Rhythmus bleibt, kann sofort wieder fällig sein) | L-11, `pets.py`/`plants.py::complete` |
| E-2 | Intervalländerung: bestehende Fälligkeit neu rechnen (`last_done_at + neues Intervall`)? | a) nein (heute) · b) ja, wenn `last_done_at` gesetzt | L-11 |
| E-3 | Pausiertes Ämtli: bereits geplante offene Zuweisungen ausblenden/löschen? | a) sichtbar lassen (heute) · b) ausblenden solange inaktiv · c) löschen | L-10 |
| E-4 | Mehrfach-Scan `plant.water` am selben Tag: erneut loggen oder `changed=false`? | a) loggen (heute) · b) idempotent pro Tag | Epic 34, Abschnitt 4 |
| E-5 | `RecurringBill.split_type` hat keine Wirkung (Buchung ist immer gleichmässig auf alle Mitglieder) | a) Feld entfernen · b) Anteile pro Rechnung modellieren · c) `custom` beim Anlegen ablehnen | L-02 |
| E-6 | Zuweisungen (Todos, Einkauf) eines ausgetretenen/entfernten Mitglieds | a) stehen lassen (heute) · b) beim Austritt auf „niemand“ setzen | L-15 |
| E-7 | Rotation eines Ämtlis beim Austritt bereinigen? | a) nein, Scheduler überspringt (heute, dokumentiert) · b) ja, inkl. Index-Korrektur | L-09 |
| E-8 | KI-Tageslimit nach UTC oder Haushaltszeit? | a) UTC (heute, dokumentiert) · b) Haushaltszeit (`household_today`) | L-17 |
| E-9 | „Fehlende Zutaten“ aus dem KI-Vorschlag gegen die Liste deduplizieren? | a) nein (heute) · b) wie beim Rezept-Endpunkt | L-12 |
| E-10 | Abstimmungs-Optionen: Zeiten in der API in Haushaltszeit liefern (wie Termine)? | a) UTC (heute) · b) Haushaltszeit | L-13 |

## Zusammenfassung

- **Geprüfte Regeln:** 136 Szenarien in 12 Modulen (Tabellen oben), davon 10 mit neuen Tests belegt (Backend `test_household_time.py` +7, `test_recurring_bill_book.py` +1, `test_poll_scoping.py` +1, `test_dashboard_scoping.py` +1, `test_chores.py` +2, `test_pet_care_scoping.py` +1; Frontend `householdScope.test.ts` +2, `auth.test.ts` +2).
- **Gefundene Fehler:** 8 — davon 2 mit falschen Geld-/Monatszuordnungen (L-01, L-02), 1 Absturz einer Ansicht (L-03), 2 falsche Anzeigen (L-04, L-07), 2 nicht mehr ausführbare Aktionen (L-05, L-08), 1 verlorene Erinnerung (L-06). Kein Datenverlust gefunden.
- **Behoben:** alle 8, je ein Commit mit Test (Backend 805 Tests, Frontend 367 Tests, Coverage 75 % Statements).
- **Unschärfen:** 9 (L-09, L-12 bis L-16 sowie drei Randfälle in den Tabellen), nicht geändert.
- **Offene Produktentscheidungen:** 10 (E-1 bis E-10).
