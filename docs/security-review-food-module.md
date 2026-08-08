# 🔒 Security Review: Food-Modul (Essen)

**Datum:** 2026-08-08  
**Reviewer:** Security-Review Agent  
**Scope:** `backend/app/routers/food.py`, `backend/app/routers/polls.py` (meal-decide), `backend/app/models.py` (Recipe, MealPlanEntry)  
**Gesamtbewertung:** ⚠️ 1× Hoch, 2× Mittel, 2× Gering — kein Kritisch

---

## Zusammenfassung

| # | Schweregrad | Finding | Datei | Zeile |
|---|------------|---------|-------|-------|
| F-1 | 🔴 **Hoch** | IDOR: `recipe_id` in Poll-Optionen nicht household-validiert | `polls.py` | 171–179 |
| F-2 | 🟠 **Mittel** | `ingredients`-Liste unbegrenzt (Anzahl + String-Länge) | `food.py` | 31, 40 |
| F-3 | 🟠 **Mittel** | Ingredient-String kann `ShoppingItem.name` (200 Zeichen) überschreiten | `food.py` | 453–454 |
| F-4 | 🟡 **Gering** | Kein Rate-Limiting auf Bulk-Endpunkt `add-missing-to-shopping` | `food.py` | 401–500 |
| F-5 | 🟡 **Gering** | `PollCreate.options` hat kein `max_length` | `polls.py` | 52 |

---

## ✅ Positiv-Befunde (kein Handlungsbedarf)

### Household-Scoping — korrekt implementiert
Alle 9 Endpoints im Food-Modul verwenden `verify_household_access` als Dependency:

| Endpoint | Method | `verify_household_access` | DB-Filter `household_id` |
|----------|--------|:-------------------------:|:------------------------:|
| `/recipes/` | POST | ✅ | ✅ |
| `/recipes/` | GET | ✅ | ✅ |
| `/recipes/{recipe_id}` | GET | ✅ | ✅ via `_get_recipe_or_404` |
| `/recipes/{recipe_id}` | PATCH | ✅ | ✅ via `_get_recipe_or_404` |
| `/recipes/{recipe_id}` | DELETE | ✅ | ✅ via `_get_recipe_or_404` |
| `/meal-plan/` | GET | ✅ | ✅ |
| `/meal-plan/{date}` | PUT | ✅ | ✅ + Recipe-Ownership-Check |
| `/meal-plan/{date}` | DELETE | ✅ | ✅ |
| `/meal-plan/{id}/add-missing-to-shopping` | POST | ✅ | ✅ via `_get_meal_plan_entry_or_404` |

### IDOR-Schutz bei Recipes + MealPlan — korrekt
- `_get_recipe_or_404()` (`food.py:110–122`): Lädt per PK, prüft `recipe.household_id != household_id` → 404.  
- `_get_meal_plan_entry_or_404()` (`food.py:125–138`): Gleiches Pattern.  
- **Kein Existenz-Leak:** Fremde Ressourcen geben 404 zurück (nicht 403).

### Upsert MealPlan — recipe_id wird validiert
In `upsert_meal_plan` (`food.py:327–328`) wird `_get_recipe_or_404(db, body.recipe_id, household_id)` aufgerufen → **Cross-Household recipe_id Injection verhindert**.

### SQL-Injection — kein Risiko
- Kein Raw-SQL im Food-Modul. Alle Queries über SQLAlchemy ORM.
- `func.lower()` (`food.py:445`) wird parameterisiert ausgeführt.
- `text()` nur in Model-Defaults (`server_default`), nicht in Queries.

### JSON-Injection in ingredients — kein Risiko
- Pydantic validiert `list[str]` strikt: verschachtelte Objekte/Arrays werden abgelehnt.
- Speicherung über SQLAlchemy JSON-Column mit korrekter Serialisierung.

### Autorisierung — korrekt für Anwendungsfall
- Alle Household-Mitglieder können CRUD auf Rezepte/MealPlan. **Gewollt:** keine Admin-Checks nötig.

### Meal-Decide Cross-Household — korrekt
- `_get_poll_or_404` filtert nach `household_id` → fremde Polls nicht entscheidbar.
- Option-Validierung (`polls.py:392–405`): `option_id` muss zum Poll gehören.

### Test-Abdeckung — gut
- `test_food_scoping.py`: 7 Cross-Household-Tests für Recipe + MealPlan.
- `test_food_shopping.py`: 5 Tests inkl. Cross-Household auf `add-missing-to-shopping`.
- `test_meal_poll.py`: Typ-Mismatch, Already-Decided, Happy-Path Tests.

---

## 🔴 F-1: IDOR via `recipe_id` in Poll-Optionen (Hoch)

**Datei:** [`polls.py`](../backend/app/routers/polls.py:171)  
**Zeilen:** 171–179

### Beschreibung
Beim Erstellen eines Polls (`create_poll`) wird `recipe_id` aus `PollOptionCreate` direkt in `EventPollOption` gespeichert — **ohne zu prüfen, ob das Rezept zum selben Household gehört.**

```python
# polls.py:171-179 — recipe_id wird NICHT validiert
for opt in body.options:
    option = EventPollOption(
        poll_id=poll.id,
        household_id=household_id,
        label=opt.label,
        starts_at=opt.starts_at,
        recipe_id=opt.recipe_id,  # ← KEINE Household-Prüfung!
    )
    db.add(option)
```

### Angriffsszenario
1. Angreifer (Household A) kennt/errät eine `recipe_id` aus Household B.
2. Erstellt einen Meal-Poll mit Option `recipe_id=<UUID_aus_Household_B>`.
3. Entscheidet den Poll via `/meal-decide`.
4. `MealPlanEntry` in Household A referenziert nun Recipe aus Household B.
5. Beim Laden des Wochenplans (`get_week_plan`) wird das Recipe via `lazy="selectin"` automatisch geladen und exponiert:
   - Name, Zutaten, Kosten, Dauer des fremden Rezepts.

### Impact
- **Vertraulichkeit:** Rezeptdaten eines fremden Households werden geleakt.
- **Voraussetzung:** Angreifer muss UUID des fremden Rezepts kennen (schwer zu erraten, aber nicht unmöglich bei URL-Leaks).

### Korrekturvorschlag

```python
# In create_poll(), nach db.flush() für den Poll:
for opt in body.options:
    # NEU: recipe_id validieren
    if opt.recipe_id is not None:
        from app.models import Recipe
        recipe = db.get(Recipe, opt.recipe_id)
        if recipe is None or recipe.household_id != household_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_detail(
                    ErrorCode.RECIPE_NOT_FOUND,
                    f"Recipe {opt.recipe_id} not found in this household",
                ),
            )
    option = EventPollOption(...)
```

### Fehlender Test
`test_meal_poll.py` enthält keinen Test, der eine `recipe_id` aus einem fremden Household in einer Poll-Option prüft. Empfehlung:

```python
def test_create_meal_poll_with_foreign_recipe_returns_400(
    client, household_a, token_a, recipe_b
):
    """Poll-Option mit recipe_id aus fremdem Household → 400."""
    resp = client.post(
        f"/api/households/{household_a.id}/polls/",
        json={
            "question": "Was essen wir?",
            "poll_type": "meal",
            "meal_date": "2026-08-15",
            "options": [
                {"label": "Fremdes Rezept", "recipe_id": str(recipe_b.id)},
                {"label": "Salat"},
            ],
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 400
```

---

## 🟠 F-2: `ingredients`-Liste unbegrenzt (Mittel)

**Datei:** [`food.py`](../backend/app/routers/food.py:31)  
**Zeilen:** 31 (RecipeCreate), 40 (RecipeUpdate)

### Beschreibung
Die `ingredients`-Feld-Definition hat **keine Begrenzung**:
- Keine `max_length` auf der Liste selbst (Anzahl Elemente).
- Keine `max_length` auf den einzelnen Strings.

```python
# food.py:31
ingredients: list[str] = Field(default_factory=list)  # ← unbegrenzt!

# food.py:40
ingredients: list[str] | None = None  # ← unbegrenzt!
```

### Angriffsszenario
Ein Angreifer sendet:
```json
{
  "name": "Evil Recipe",
  "ingredients": ["A".repeat(1000000)] // 1 MB pro String
}
```
Oder 10.000 Strings → DB-Bloat, langsame JSON-Serialisierung, Memory-Pressure.

### Impact
- **Verfügbarkeit:** DoS durch DB-Bloat und Memory-Verbrauch.
- **Einfachheit:** Trivial ausnutzbar mit einem einzelnen API-Call.

### Korrekturvorschlag

```python
from pydantic import field_validator

class RecipeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    servings: int = Field(default=2, ge=1)
    cost_rappen: int | None = Field(None, ge=0)
    duration_min: int | None = Field(None, ge=1)
    ingredients: list[str] = Field(default_factory=list, max_length=100)  # max 100 Zutaten
    is_favorite: bool = False

    @field_validator("ingredients")
    @classmethod
    def validate_ingredients(cls, v: list[str]) -> list[str]:
        for i, item in enumerate(v):
            if len(item) > 200:
                raise ValueError(f"Ingredient {i} exceeds 200 characters")
            if not item.strip():
                raise ValueError(f"Ingredient {i} must not be blank")
        return [item.strip() for item in v]
```

Gleiches für `RecipeUpdate`.

---

## 🟠 F-3: Ingredient überschreitet `ShoppingItem.name` Limit (Mittel)

**Datei:** [`food.py`](../backend/app/routers/food.py:453)  
**Zeilen:** 453–454

### Beschreibung
In `add_missing_to_shopping` wird `ingredient` direkt als `ShoppingItem.name` gespeichert:

```python
# food.py:453-454
item = ShoppingItem(
    ...
    name=ingredient,  # ← kann > 200 Zeichen sein
    ...
)
```

`ShoppingItem.name` ist `String(200)` (`models.py:169`). Wenn ein Ingredient-String > 200 Zeichen ist, wird je nach DB-Engine:
- **PostgreSQL (strict):** `DataError` → 500 Internal Server Error.
- **SQLite (lenient):** Silently truncated oder gespeichert.

### Impact
- **Verfügbarkeit:** Unbehandelter 500-Fehler bei zu langen Ingredients.
- **Integrität:** Stille Truncation je nach DB.

### Korrekturvorschlag
Wird durch F-2 (Ingredient-Validierung) automatisch behoben. Zusätzlich als Defense-in-Depth:

```python
# food.py, in add_missing_to_shopping loop:
ingredient = raw_ingredient.strip()[:200]  # Truncation als Fallback
```

---

## 🟡 F-4: Kein Rate-Limiting auf Bulk-Endpunkt (Gering)

**Datei:** [`food.py`](../backend/app/routers/food.py:401)  
**Kontext:** [`main.py`](../backend/app/main.py:1) — kein globales Rate-Limiting

### Beschreibung
`add_missing_to_shopping` erstellt bis zu N `ShoppingItem`-Rows pro Aufruf (N = Anzahl Ingredients). In Kombination mit F-2 (unbegrenzte Ingredients-Liste) könnte ein Angreifer:
1. Ein Rezept mit 1000 Zutaten erstellen.
2. `add-missing-to-shopping` aufrufen → 1000 DB-Inserts + 1000 Socket-Events.

Zudem gibt es **kein globales Rate-Limiting** in der gesamten App (`slowapi` o.ä. nicht vorhanden).

### Impact
- **Verfügbarkeit:** Gering, da Authentifizierung erforderlich und Household-Scoping die Blast-Radius begrenzt.

### Korrekturvorschlag
1. **Kurzfristig:** F-2 beheben (max 100 Ingredients) → begrenzt automatisch die Bulk-Erstellung.
2. **Mittelfristig:** Globales Rate-Limiting mit `slowapi` oder ähnlichem einführen (z.B. 60 req/min pro User).

---

## 🟡 F-5: `PollCreate.options` ohne Obergrenze (Gering)

**Datei:** [`polls.py`](../backend/app/routers/polls.py:52)

### Beschreibung
```python
# polls.py:52
options: list[PollOptionCreate] = Field(..., min_length=2)  # ← kein max_length!
```

Ein Angreifer könnte einen Poll mit Tausenden von Optionen erstellen → DB-Bloat.

### Korrekturvorschlag
```python
options: list[PollOptionCreate] = Field(..., min_length=2, max_length=20)
```

---

## Nicht-Findings (explizit geprüft und OK)

| Prüfpunkt | Ergebnis |
|-----------|----------|
| `verify_household_access` auf allen Endpoints | ✅ Korrekt |
| DB-Queries filtern nach `household_id` | ✅ Korrekt |
| IDOR über `recipe_id` in `upsert_meal_plan` | ✅ Geschützt via `_get_recipe_or_404` |
| IDOR über `entry_id` in `add-missing-to-shopping` | ✅ Geschützt via `_get_meal_plan_entry_or_404` |
| SQL-Injection | ✅ Kein Raw-SQL, nur ORM |
| JSON-Injection in `ingredients` | ✅ Pydantic validiert `list[str]` |
| Cross-Household MealPlan-Delete | ✅ Filter auf `household_id` + `date` |
| Meal-Poll Decide: Poll-Ownership | ✅ `_get_poll_or_404` filtert `household_id` |
| Meal-Poll Decide: Option-Ownership | ✅ Loop prüft `opt.id == body.option_id` innerhalb des Polls |
| `free_text` max_length | ✅ `max_length=150` auf Pydantic + DB `String(150)` |
| `name` max_length | ✅ `max_length=150` auf Pydantic + DB `String(150)` |
| `duration_min` ge=1 | ✅ Korrekt |
| `cost_rappen` ge=0 | ✅ Korrekt |
| Fehler-Responses leaken keine Interna | ✅ Nur ErrorCode + generische Message |

---

## Empfohlene Prioritätsreihenfolge

1. **F-1** (Hoch) — IDOR-Fix in `create_poll`: `recipe_id` validieren + Test schreiben.
2. **F-2** (Mittel) — `ingredients` begrenzen: `max_length=100` auf Liste + 200 Zeichen pro String.
3. **F-3** (Mittel) — Wird durch F-2 automatisch gelöst; ggf. Truncation als Fallback.
4. **F-5** (Gering) — `max_length=20` auf Poll-Optionen.
5. **F-4** (Gering) — Globales Rate-Limiting (betrifft gesamte App, nicht nur Food-Modul).
