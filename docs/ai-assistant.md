# KI-Assistent

**Stand:** 2026-10-06 · **Branch:** `claude/ai-assistant` · **Status:** Etappe 1 umgesetzt (Rezeptvorschlag, Pflanzenpflege)

Der KI-Assistent ist optional. Ohne `ANTHROPIC_API_KEY` blendet das Frontend alle KI-Elemente aus und die App funktioniert unverändert. Mit Schlüssel muss zusätzlich ein Admin den Assistenten pro Haushalt einschalten (Opt-in).

Sicherheitsbewertung: [`docs/security/ai-assistant-review.md`](security/ai-assistant-review.md).

---

## 1. Überblick

| Funktion | Endpunkt | Effort | `max_tokens` | Ergebnis |
|---|---|---|---|---|
| Rezept erzeugen | `POST /api/households/{id}/ai/recipe` | `medium` | 8000 | Vorschlag im Format von `RecipeCreate`, nicht gespeichert |
| Pflanzenpflege | `POST /api/households/{id}/ai/plant-care` | `low` | 4000 | `PlantCareAdvice` (Intervalle, Licht, Giftigkeit) |
| Status | `GET /api/ai/status` | — | — | `{enabled, daily_limit}`; `enabled=false` ohne Schlüssel |
| Einstellungen lesen | `GET /api/households/{id}/ai/settings` | — | — | Opt-in, Verfügbarkeit, Aufrufe heute, Tageslimit (alle Mitglieder) |
| Opt-in setzen | `PUT /api/households/{id}/ai/settings` | — | — | nur Admins; sendet `household_updated` mit `ai_enabled` |

`max_tokens` ist bei Rezepten bewusst grösser als die geschätzten ~4000 Token Antwort: Bei Claude Opus 5.5 ist Denken immer an und zählt zu `max_tokens`. Abgerechnet wird nur, was tatsächlich erzeugt wird.

## 2. Architektur

```
Frontend (Vue)                          Backend (FastAPI)                         Anthropic-API
──────────────                          ─────────────────                         ─────────────
AiRecipeCard / AssistantView
  → stores/ai.ts
  → repositories/aiRepository.ts ──►  routers/ai.py
                                         1. verify_household_access (Mitglied)
                                         2. Schlüssel gesetzt?        → 503 AI_NOT_CONFIGURED
                                         3. household.ai_enabled?     → 403 AI_NOT_ENABLED
                                         4. slowapi 10/min pro IP     → 429 RATE_LIMITED
                                         5. usage.reserve_call        → 429 AI_DAILY_LIMIT_REACHED
                                       services/ai/recipe.py | plant_care.py
                                         prompts.py (System DE/EN, Eingaben als JSON-Daten)
                                       services/ai/client.py
                                         call_structured() ─────────────────►  POST /v1/messages?beta=true
                                                                                  model claude-opus-5-5
                                                                                  output_config {effort, format}
                                                                                  fallbacks "default"
                                         ◄──────────────── geparstes Pydantic-Modell
                                         usage.record_tokens (response.usage)
  ◄── Vorschlag zur Prüfung ─────────
„Speichern“ → POST /recipes/ (bestehend)
„Fehlende auf Einkaufsliste“ → POST /shopping-items/ (bestehend)
```

### Dateien

| Datei | Inhalt |
|---|---|
| `backend/app/services/ai/client.py` | Client-Factory (`get_client`), `call_structured` (der einzige API-Aufruf), Fehler-Mapping der SDK-Exceptions, Begrenzung gleichzeitiger Aufrufe |
| `backend/app/services/ai/prompts.py` | Systemprompts DE/EN, `render_input` (Nutzereingaben als escapter JSON-Block) |
| `backend/app/services/ai/schemas.py` | Request-Modelle, Output-Modelle für die API (`RecipeOutput`, `PlantCareOutput`), Antwort-Modelle |
| `backend/app/services/ai/recipe.py`, `plant_care.py` | je eine Funktion pro Feature + Abbildung der Modell-Ausgabe auf die App-Schemas |
| `backend/app/services/ai/usage.py` | Tageslimit und Token-Zähler (`ai_usage`) |
| `backend/app/services/ai/errors.py` | fachliche Fehler (`AiRefused`, `AiInvalidOutput`, …) |
| `backend/app/routers/ai.py` | Endpunkte, Prüfreihenfolge, Fehler → HTTP |
| `frontend/src/stores/ai.ts`, `repositories/aiRepository.ts` | Store und API-Zugriff |
| `frontend/src/components/AiRecipeCard.vue` | Rezeptvorschlag in der Essen-Ansicht |
| `frontend/src/components/AiSettingsCard.vue` | Opt-in in den Haushaltseinstellungen |
| `frontend/src/views/AssistantView.vue` | `/assistant` mit Pflanzenpflege |

### API-Aufruf

Alle Funktionen gehen durch `call_structured` (`client.py`):

```python
client.beta.messages.parse(
    model="claude-opus-5-5",
    max_tokens=max_tokens,
    system=SYSTEM_PROMPT[locale],
    messages=[{"role": "user", "content": user_content}],
    output_config={"effort": effort},       # SDK ergänzt format = JSON-Schema des Pydantic-Modells
    output_format=OutputModel,
    betas=["server-side-fallback-2026-07-01"],
    fallbacks="default",
)
```

- **Kein Textparsing:** Das SDK schickt das Pydantic-Modell als JSON-Schema (`output_config.format`) und validiert die Antwort. Übernommen wird nur `response.parsed_output`.
- **Kein `thinking`-Parameter, kein `budget_tokens`, kein Prefill, kein erzwungenes `tool_choice`.** Die Tiefe steuert `output_config.effort`.
- **Serverseitige Fallbacks:** Lehnt ein Sicherheits-Klassifikator ab, beantwortet die API die Anfrage im selben Aufruf mit dem von Anthropic empfohlenen Ersatzmodell. Lehnt auch dieses ab, ist `stop_reason == "refusal"` → 422 `AI_REFUSED`.
- **Client:** `anthropic.Anthropic(api_key=…, timeout=90, max_retries=1)`. Der Schlüssel wird explizit aus `settings.anthropic_api_key` übergeben.
- **Gleichzeitige Aufrufe:** höchstens `AI_MAX_CONCURRENT_REQUESTS` (Standard 4) pro Prozess, sonst sofort 503 `AI_BUSY`. Jeder Aufruf belegt einen Worker-Thread des sync Endpoints.

### Fehler

| Ursache | HTTP | Code | Zählt zum Tageslimit |
|---|---|---|---|
| kein Schlüssel | 503 | `AI_NOT_CONFIGURED` | nein |
| Haushalt hat nicht eingeschaltet | 403 | `AI_NOT_ENABLED` | nein |
| Tageslimit erreicht | 429 | `AI_DAILY_LIMIT_REACHED` | — |
| IP-Limit (10/min) | 429 | `RATE_LIMITED` | nein |
| `stop_reason == "refusal"` | 422 | `AI_REFUSED` | ja (Tokens aus `usage`) |
| Pflanze nicht erkannt (`recognized=false`) | 422 | `AI_PLANT_NOT_RECOGNIZED` | ja |
| Antwort passt nicht ins Schema / `max_tokens` erreicht / unbrauchbar | 502 | `AI_INVALID_OUTPUT` | ja |
| `RateLimitError` des Anbieters, zu viele gleichzeitige Aufrufe | 503 | `AI_BUSY` | nein |
| `APIConnectionError` / `APITimeoutError` / sonstiger `APIStatusError` | 502 | `AI_UNAVAILABLE` | nein |

Details zu Status-Fehlern (Statuscode, `request_id`) landen nur im Server-Log, nie in der Antwort.

## 3. Datenfluss und Datenschutz

**Was an die Anthropic-API geht:**

| Funktion | Gesendet | Nicht gesendet |
|---|---|---|
| Rezept | Zutatenliste, Personenzahl, Wünsche (vegetarisch, schnell, Kinder, Reste), optionale Notiz, Sprache | Haushaltsname, Nutzer, E-Mail, bestehende Rezepte, Einkaufsliste |
| Pflanzenpflege | Pflanzenname/-art, optionaler Standort, Sprache | wie oben |

- **Opt-in pro Haushalt:** `households.ai_enabled` ist standardmässig `false`. Nur Admins schalten um. Die Einstellungskarte zeigt den Hinweis, dass Eingaben (Zutaten, Pflanzenart, später Fotos) an die Anthropic-API gesendet werden.
- **Keine Speicherung von Ein- oder Ausgaben im Backend.** Gespeichert werden nur Zähler (`ai_usage`: Tag, Haushalt, Aufrufe, Tokens). Ein Rezept landet erst in der Datenbank, wenn jemand auf „Speichern“ tippt.
- **Der Schlüssel bleibt im Backend.** Das Frontend ruft nie den Anbieter direkt; die CSP (`connect-src 'self'`) würde das auch blockieren.
- Für die Verarbeitung bei Anthropic gelten deren Bedingungen für die kommerzielle API. Wer den Assistenten in Betrieb nimmt, sollte die Haushaltsmitglieder darüber informieren (der Hinweistext in den Einstellungen ist der Ausgangspunkt).

## 4. Kosten

Preise Claude Opus 5.5 (Stand 2026-09): **4 USD pro Mio. Input-Tokens, 20 USD pro Mio. Output-Tokens** (Denk-Tokens zählen als Output). Fällt eine Anfrage auf ein Ersatzmodell zurück, gilt dessen Preis.

**Schätzung pro Aufruf** (nicht gemessen, siehe unten):

| Funktion | Input | Output (inkl. Denken) | Kosten ca. |
|---|---|---|---|
| Rezept (`medium`) | ~800 | 1500–3500 | 0,03–0,07 USD |
| Pflanzenpflege (`low`) | ~700 | 400–1000 | 0,01–0,02 USD |

**Obergrenze pro Haushalt:** `AI_DAILY_LIMIT_PER_HOUSEHOLD=50` × ~0,07 USD ≈ **3,50 USD pro Tag** im ungünstigsten Fall (nur Rezepte). Ein Haushalt mit ein paar Anfragen pro Woche liegt bei wenigen Rappen im Monat.

**Messung:** In der Entwicklungsumgebung dieses Branches war kein `ANTHROPIC_API_KEY` gesetzt; es gab **keinen echten API-Aufruf**, die Token-Zahlen oben sind Schätzungen. Echte Werte stehen nach den ersten Aufrufen in der Tabelle `ai_usage` (und im Log: `AI call ok model=… input_tokens=… output_tokens=…`):

```sql
SELECT day, SUM(calls) AS calls, SUM(input_tokens) AS input, SUM(output_tokens) AS output,
       ROUND(SUM(input_tokens) * 4.0 / 1e6 + SUM(output_tokens) * 20.0 / 1e6, 4) AS usd
FROM ai_usage GROUP BY day ORDER BY day DESC;
```

Prompt-Caching bringt hier nichts: Die Systemprompts liegen unter der Mindestlänge für einen Cache-Eintrag.

## 5. Kostenschutz

1. **IP-Limit:** slowapi `10/minute` auf `/ai/recipe` und `/ai/plant-care` (in-memory, wie die übrigen Limits).
2. **Tageslimit pro Haushalt:** `ai_usage` mit einer Zeile pro Haushalt und UTC-Tag. `reserve_call` erhöht `calls` per `UPDATE … WHERE calls < limit` — auch parallele Anfragen überschreiten das Limit nicht (mit 10 parallelen Anfragen gegen PostgreSQL geprüft: genau `limit` kommen durch). Kam keine Antwort der API zustande (Netzwerk, Überlast, Fehlerstatus), wird die Reservierung zurückgegeben.
3. **Gleichzeitige Aufrufe** pro Prozess begrenzt (Abschnitt 2).
4. **Bekannte Lücke:** Wer einen Account hat, kann weitere Haushalte gründen und dort den Assistenten einschalten. Ein Limit pro Nutzer oder ein globales Tageslimit fehlt noch (Review A-01).

## 6. Konfiguration

| Variable | Standard | Bedeutung |
|---|---|---|
| `ANTHROPIC_API_KEY` | leer | Schlüssel von <https://console.anthropic.com>; leer = KI deaktiviert |
| `AI_DAILY_LIMIT_PER_HOUSEHOLD` | `50` | Aufrufe pro Haushalt und UTC-Tag; `0` sperrt alle Aufrufe |
| `AI_REQUEST_TIMEOUT_SECONDS` | `90` | Timeout pro Versuch; das SDK wiederholt höchstens einmal |
| `AI_MAX_CONCURRENT_REQUESTS` | `4` | gleichzeitige KI-Aufrufe pro Backend-Prozess |

Dev: in `.env` (wird von `docker-compose.yml` durchgereicht). Produktion: in `.env.prod` (`env_file`).

**Reverse-Proxy:** Eine Rezept-Antwort kann länger als 60 Sekunden dauern. `frontend/nginx.conf` setzt für `/api/households/*/ai/` `proxy_read_timeout 200s`. Liegt davor noch Nginx Proxy Manager, dort für den Host ebenfalls ein längeres Timeout eintragen (Custom Nginx Configuration: `proxy_read_timeout 200s;`), sonst bricht der Browser nach dem NPM-Timeout ab, obwohl der Aufruf abgerechnet wird.

## 7. Ausgabe-Schemas

### Rezept (`RecipeSuggestionResponse`)

```json
{
  "recipe": {
    "name": "Zucchetti-Risotto",
    "servings": 4,
    "cost_rappen": null,
    "duration_min": 35,
    "ingredients": ["300 g Risottoreis", "2 Zucchetti", "1 Zwiebel"],
    "steps": ["Zwiebel andünsten.", "Reis zugeben …"],
    "tags": ["vegetarisch", "Reste verwerten"],
    "is_favorite": false
  },
  "missing_ingredients": [{ "name": "Parmesan", "quantity": "50 g" }],
  "tip": "Mit etwas Zitronenschale servieren."
}
```

`recipe` hat genau die Felder von `RecipeCreate` und geht unverändert an `POST /api/households/{id}/recipes/`. Dafür haben Rezepte neu die Felder `steps` und `tags` (Migration `c8d9e0f1a2b3`); bestehende Rezepte haben leere Listen. `missing_ingredients` passt auf `ShoppingItemCreate` (`name` ≤ 200, `quantity` ≤ 50).

Die Modell-Ausgabe (`RecipeOutput`) wird vor der Rückgabe in die Grenzen von `RecipeCreate` gebracht: Texte gekürzt, leere Einträge entfernt, höchstens 100 Zutaten / 30 Schritte / 10 Tags, ungültige Portionen → gewünschte Personenzahl, ungültige Dauer → `null`. Ein Rezept ohne Zutaten oder Schritte ist `AI_INVALID_OUTPUT`.

### Pflanzenpflege (`PlantCareAdvice`) — Vorlage für das Pflanzen-Modul

| Feld | Typ | Bedeutung |
|---|---|---|
| `plant_name` | string ≤ 100 | gebräuchlicher Name (Fallback: Eingabe) |
| `botanical_name` | string ≤ 100 \| null | botanischer Name |
| `watering_interval_days` | int 1–365 | Gießabstand in der Wachstumszeit |
| `fertilizing_interval_days` | int 1–365 \| null | Düngeabstand; `null` = kein Dünger nötig |
| `repotting_interval_months` | int 1–120 \| null | Umtopf-Abstand; `null` = unüblich |
| `light` | `low` \| `medium` \| `bright_indirect` \| `full_sun` | Lichtbedarf |
| `location_tip` | string ≤ 500 | Standort-Tipp (berücksichtigt den angegebenen Standort) |
| `care_notes` | string ≤ 1500 | Pflegehinweise inkl. Winterpflege |
| `pet_toxicity` | `unknown` \| `non_toxic` \| `toxic` | Giftigkeit für Katzen/Hunde; `unknown`, wenn nicht gesichert |
| `pet_toxicity_note` | string ≤ 500 \| null | kurzer Hinweis |

Die Oberfläche zeigt zur Giftigkeit immer „Keine tierärztliche Auskunft“.

**Einbindung im Pflanzen-Modul (Branch `claude/plants-module`):** Der Endpunkt ist bewusst unabhängig von einem `Plant`-Modell. Beim Anlegen einer Pflanze kann das Modul `POST /ai/plant-care` mit dem Namen aufrufen und die Pflegeaufgaben vorbefüllen: Gießen alle `watering_interval_days` Tage, Düngen alle `fertilizing_interval_days` Tage (falls nicht `null`), Umtopfen alle `repotting_interval_months` Monate; `light`, `location_tip`, `care_notes` und `pet_toxicity` als Felder bzw. Notiz der Pflanze. Der Nutzer bestätigt die Werte, bevor sie gespeichert werden.

## 8. Weitere Funktionen ergänzen

1. **Schemas** in `services/ai/schemas.py`: Request-Modell (mit Längengrenzen) und Output-Modell (`…Output`, mit `Field(description=…)`, ohne harte Grenzen — die setzt der nächste Schritt durch).
2. **Prompt** in `prompts.py`: Systemprompt DE/EN mit `_DATA_RULE` anhängen; Nutzernachricht über `render_input(intro, data)` bauen. Nie Nutzerdaten in den Systemprompt.
3. **Feature-Funktion** `services/ai/<feature>.py`: `call_structured(...)` mit passendem `effort` (`low` für einfache Nachschlage-Aufgaben, `medium` für kreative/mehrteilige), Ausgabe in das App-Schema abbilden; bei Unbrauchbarem `AiInvalidOutput(…, result.usage)` werfen.
4. **Endpunkt** in `routers/ai.py`: `Depends(require_ai_enabled)`, `@limiter.limit(AI_RATE_LIMIT)`, `_run_feature(db, household_id, feature, body)`. Neue fachliche Fehler in `_ERROR_MAP` eintragen, Codes in `ErrorCode` und `errors.*` (DE/EN).
5. **Frontend:** Repository-Methode, Store-Action (Fehler als Code speichern), UI nur bei `aiStore.enabledForHousehold`.
6. **Tests:** `ai_client.get_client` mocken (Fixture `fake_client` in `tests/test_ai_assistant.py`), mindestens Erfolg, Opt-in, Mitgliedschaft, Refusal, Schema-Abbildung.

## 9. Geplant: Etappe 2

| Funktion | Idee | Offene Punkte |
|---|---|---|
| **Beleg-Scan per Foto** | Kassenzettel fotografieren → Ausgabe vorbefüllen (Betrag, Datum, Geschäft, Kategorie, optional Positionen). Bild als `image`-Block (Base64) an `call_structured`, Ausgabe-Schema passend zu `ExpenseCreate`. | Bildgrösse/-format begrenzen (Upload-Infrastruktur wiederverwenden, EXIF entfernen), höhere Input-Kosten pro Bild, Hinweistext „Fotos“ ist bereits im Opt-in enthalten; Beträge in Rappen und Haushaltswährung validieren |
| **Wochenplan-Vorschlag** | Aus Favoriten, vorhandenen Rezepten und Wünschen einen Wochenplan vorschlagen; Übernahme über `PUT /meal-plan/{date}`. | Welche Rezeptdaten an die API gehen (nur Namen/Tags), Abgleich mit bestehenden Einträgen, `effort` `medium` |

Für beide gilt das gleiche Muster wie in Abschnitt 8; der Datenschutz-Hinweis in den Einstellungen muss vor dem Freischalten aktualisiert werden, falls weitere Datenarten hinzukommen.
