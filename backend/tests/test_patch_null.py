"""F0-3 / CASA-04 / CASA-37: explizites ``null`` auf NOT-NULL-Feldern in PATCH → 422, Zeile unverändert.

Die Feldliste wird aus der Nullability der Modellspalten abgeleitet: jede neue
NOT-NULL-Spalte, die ein ``*Update``-Schema anbietet, ist automatisch abgedeckt.
``test_every_patch_body_is_covered`` stellt sicher, dass neue PATCH-Endpunkte hier
registriert werden.
"""

import importlib
import pkgutil
import uuid
from datetime import date, timedelta

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute
from sqlalchemy import inspect as sa_inspect

import app.routers as routers_pkg
from app.core.patch_schema import PatchModel
from app.models import (
    Calendar,
    Chore,
    Document,
    Event,
    Expense,
    Medication,
    Note,
    Pet,
    PetCareTask,
    Plant,
    PlantCareTask,
    Recipe,
    RecurringBill,
    ShoppingItem,
    ShoppingList,
    Tag,
    Todo,
)
from app.routers import (
    calendars,
    chores,
    documents,
    events,
    expenses,
    food,
    notes,
    pets,
    plants,
    recurring_bills,
    shopping,
    tags,
    todos,
)

# Felder, deren null bewusst umgedeutet wird (null → leere Liste), statt 422
COERCED_TO_EMPTY_LIST = {(food.RecipeUpdate, "ingredients"), (food.RecipeUpdate, "steps"), (food.RecipeUpdate, "tags")}


# --------------------------------------------------------------------------
# Setup je Schema: liefert (Pfad-Parameter, ORM-Objekt)
# --------------------------------------------------------------------------


def _chore(db, hh, user):
    c = Chore(id=uuid.uuid4(), household_id=hh.id, title="Bad putzen", recurrence="weekly", weekday=0,
              rotation_order=[str(user.id)], anchor_date=date.today())
    db.add(c)
    db.commit()
    return {"chore_id": c.id}, c


def _pet_care_task(db, hh, pet):
    t = PetCareTask(id=uuid.uuid4(), household_id=hh.id, pet_id=pet.id, name="Krallen",
                    interval_days=14, next_due_at=date.today() + timedelta(days=3))
    db.add(t)
    db.commit()
    return {"pet_id": pet.id, "task_id": t.id}, t


def _plant_care_task(db, hh, plant):
    t = PlantCareTask(id=uuid.uuid4(), household_id=hh.id, plant_id=plant.id, care_type="water",
                      interval_days=7, next_due_at=date.today() + timedelta(days=2))
    db.add(t)
    db.commit()
    return {"plant_id": plant.id, "task_id": t.id}, t


def _tag(db, hh, user, todo):
    t = Tag(id=uuid.uuid4(), household_id=hh.id, token=uuid.uuid4().hex, label="Küche",
            target_type="todo", target_id=todo.id, action="todo.done", created_by_user_id=user.id)
    db.add(t)
    db.commit()
    return {"tag_id": t.id}, t


# (Schema, Modell, Setup(request, db) → (Pfad-Parameter, Objekt))
CASES = [
    (calendars.CalendarUpdate, Calendar, lambda r, db: ({"calendar_id": r.getfixturevalue("calendar_a").id}, r.getfixturevalue("calendar_a"))),
    (chores.ChoreUpdate, Chore, lambda r, db: _chore(db, r.getfixturevalue("household_a"), r.getfixturevalue("user_a"))),
    (documents.DocumentUpdate, Document, lambda r, db: ({"document_id": r.getfixturevalue("document_a").id}, r.getfixturevalue("document_a"))),
    (events.EventUpdate, Event, lambda r, db: ({"event_id": r.getfixturevalue("event_a").id}, r.getfixturevalue("event_a"))),
    (expenses.ExpenseUpdate, Expense, lambda r, db: ({"expense_id": r.getfixturevalue("expense_a").id}, r.getfixturevalue("expense_a"))),
    (food.RecipeUpdate, Recipe, lambda r, db: ({"recipe_id": r.getfixturevalue("recipe_a").id}, r.getfixturevalue("recipe_a"))),
    (notes.NoteUpdate, Note, lambda r, db: ({"note_id": r.getfixturevalue("note_a").id}, r.getfixturevalue("note_a"))),
    (pets.PetUpdate, Pet, lambda r, db: ({"pet_id": r.getfixturevalue("pet_a").id}, r.getfixturevalue("pet_a"))),
    (pets.MedicationUpdate, Medication, lambda r, db: ({"pet_id": r.getfixturevalue("pet_a").id, "medication_id": r.getfixturevalue("medication_a").id}, r.getfixturevalue("medication_a"))),
    (pets.CareTaskUpdate, PetCareTask, lambda r, db: _pet_care_task(db, r.getfixturevalue("household_a"), r.getfixturevalue("pet_a"))),
    (plants.PlantUpdate, Plant, lambda r, db: ({"plant_id": r.getfixturevalue("plant_a").id}, r.getfixturevalue("plant_a"))),
    (plants.CareTaskUpdate, PlantCareTask, lambda r, db: _plant_care_task(db, r.getfixturevalue("household_a"), r.getfixturevalue("plant_a"))),
    (recurring_bills.RecurringBillUpdate, RecurringBill, lambda r, db: ({"bill_id": r.getfixturevalue("bill_a").id}, r.getfixturevalue("bill_a"))),
    (shopping.ShoppingListUpdate, ShoppingList, lambda r, db: ({"list_id": r.getfixturevalue("shopping_list_a").id}, r.getfixturevalue("shopping_list_a"))),
    (shopping.ShoppingItemUpdate, ShoppingItem, lambda r, db: ({"item_id": r.getfixturevalue("shopping_item_a").id}, r.getfixturevalue("shopping_item_a"))),
    (tags.TagUpdate, Tag, lambda r, db: _tag(db, r.getfixturevalue("household_a"), r.getfixturevalue("user_a"), r.getfixturevalue("todo_a"))),
    (todos.TodoUpdate, Todo, lambda r, db: ({"todo_id": r.getfixturevalue("todo_a").id}, r.getfixturevalue("todo_a"))),
]


def _patch_routes():
    """(Schema-Klasse, Pfad) aller PATCH-Endpunkte aus app.routers.*."""
    found = []
    for info in pkgutil.iter_modules(routers_pkg.__path__):
        mod = importlib.import_module(f"app.routers.{info.name}")
        for obj in vars(mod).values():
            if not isinstance(obj, APIRouter):
                continue
            for route in obj.routes:
                if isinstance(route, APIRoute) and "PATCH" in route.methods:
                    for param in route.dependant.body_params:
                        found.append((param.field_info.annotation, route.path))
    return found


_ROUTE_BY_SCHEMA = {schema: path for schema, path in _patch_routes()}


def _non_nullable_fields(schema, model):
    columns = model.__table__.columns
    return sorted(
        name for name in schema.model_fields
        if name in columns and not columns[name].nullable
    )


PARAMS = [
    pytest.param(schema, model, setup, field, id=f"{schema.__module__.rsplit('.', 1)[-1]}.{schema.__name__}.{field}")
    for schema, model, setup in CASES
    for field in _non_nullable_fields(schema, model)
    if (schema, field) not in COERCED_TO_EMPTY_LIST
]


def _snapshot(db, obj):
    db.expire_all()
    db.refresh(obj)
    return {attr.key: getattr(obj, attr.key) for attr in sa_inspect(obj).mapper.column_attrs}


def _url(schema, household_id, params):
    return _ROUTE_BY_SCHEMA[schema].format(household_id=household_id, **params)


@pytest.mark.parametrize(("schema", "model", "setup", "field"), PARAMS)
def test_patch_null_on_non_nullable_field_is_422(request, client, db, household_a, token_a, schema, model, setup, field):
    params, obj = setup(request, db)
    before = _snapshot(db, obj)

    r = client.patch(
        _url(schema, household_a.id, params),
        json={field: None},
        headers={"Authorization": f"Bearer {token_a}"},
    )

    assert r.status_code == 422, r.text
    assert _snapshot(db, obj) == before


def test_param_list_covers_reported_fields():
    """Die aus dem Audit bekannten Felder (CASA-04/37) sind in der Matrix."""
    ids = {p.id for p in PARAMS}
    for expected in (
        "events.EventUpdate.participant_ids",
        "events.EventUpdate.calendar_id",
        "events.EventUpdate.starts_at",
        "shopping.ShoppingItemUpdate.name",
        "shopping.ShoppingItemUpdate.is_checked",
        "expenses.ExpenseUpdate.amount_rappen",
        "expenses.ExpenseUpdate.expense_date",
        "recurring_bills.RecurringBillUpdate.amount_rappen",
        "todos.TodoUpdate.tags",
        "chores.ChoreUpdate.rotation_order",
        "food.RecipeUpdate.name",
    ):
        assert expected in ids


def test_recipe_list_fields_null_become_empty(client, db, household_a, token_a, recipe_a):
    """ingredients/steps/tags: null wird wie bei steps/tags schon bisher zu [] (nie JSON-null)."""
    r = client.patch(
        f"/api/households/{household_a.id}/recipes/{recipe_a.id}",
        json={"ingredients": None, "steps": None, "tags": None},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ingredients"] == []
    db.expire_all()
    db.refresh(recipe_a)
    assert recipe_a.ingredients == [] and recipe_a.steps == [] and recipe_a.tags == []
    listed = client.get(f"/api/households/{household_a.id}/recipes/", headers={"Authorization": f"Bearer {token_a}"})
    assert listed.status_code == 200


def test_nullable_fields_still_clearable(client, db, household_a, token_a, event_a, shopping_item_a):
    """Nullable Felder lassen sich weiterhin mit null leeren (kein Over-Blocking)."""
    headers = {"Authorization": f"Bearer {token_a}"}
    r = client.patch(f"/api/households/{household_a.id}/events/{event_a.id}", json={"note": None, "ends_at": None}, headers=headers)
    assert r.status_code == 200, r.text
    r = client.patch(f"/api/households/{household_a.id}/shopping-items/{shopping_item_a.id}", json={"quantity": None, "category": None}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["quantity"] is None


def test_every_patch_body_is_covered():
    """Jeder PATCH-Body mit optionalen Feldern erbt von PatchModel und steht in CASES."""
    covered = {schema for schema, _, _ in CASES}
    for schema, path in _patch_routes():
        has_optional = any(not f.is_required() for f in schema.model_fields.values())
        if not has_optional:
            continue
        assert issubclass(schema, PatchModel), f"{schema.__qualname__} ({path}) must extend PatchModel"
        assert schema in covered, f"{schema.__qualname__} ({path}) missing in CASES"


def test_patch_model_derives_fields_from_orm_model():
    assert "participant_ids" in events.EventUpdate.__non_nullable_fields__
    assert "note" not in events.EventUpdate.__non_nullable_fields__
    # Kein Spaltenpendant → nicht gesperrt (participant_ids: null = alle Mitglieder)
    assert "participant_ids" not in expenses.ExpenseUpdate.__non_nullable_fields__


@pytest.mark.parametrize(
    ("fixture", "attr"),
    [("event_a", "participant_ids"), ("recipe_a", "ingredients"), ("recipe_a", "steps"),
     ("recipe_a", "tags"), ("todo_a", "tags")],
)
def test_not_null_json_columns_reject_python_none(request, db, fixture, attr):
    """Zweites Netz: None auf NOT-NULL-JSON-Spalten wird SQL-NULL → Constraint greift
    (statt still das JSON-Literal 'null' zu speichern, CASA-04)."""
    from sqlalchemy.exc import IntegrityError

    obj = request.getfixturevalue(fixture)
    setattr(obj, attr, None)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
