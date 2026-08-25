"""
Zentrale Test-Konfiguration: SQLite in-memory DB, Fixtures für Multi-Tenant-Tests.

WICHTIG: Umgebungsvariablen werden VOR allen App-Imports gesetzt,
da app.core.config.Settings beim Import ausgewertet wird.
"""

import os
import uuid

# --------------------------------------------------------------------------
# 1) Env-Vars setzen BEVOR die App importiert wird
# --------------------------------------------------------------------------
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-only-for-tests")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")

# --------------------------------------------------------------------------
# 2) UUID-Compiler-Hook: PostgreSQL UUID → SQLite CHAR(36)
# --------------------------------------------------------------------------
from sqlalchemy.dialects.postgresql import UUID as PG_UUID  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402


@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


# --------------------------------------------------------------------------
# 3) App- und DB-Imports (NACH Env-Vars und Compiler-Hook)
# --------------------------------------------------------------------------
import pytest  # noqa: E402
from unittest.mock import patch  # noqa: E402

from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.models import Household, User, HouseholdMember, RefreshToken, ShoppingItem, ShoppingList, Todo, TodoReminder, Expense, ExpenseShare, Settlement, Budget, RecurringBill, Chore, ChoreAssignment, Calendar, Event, EventPoll, EventPollOption, EventPollVote, Pet, FeedingLog, Medication, MedicationLog, PetCareTask, Recipe, MealPlanEntry, Note, StoredFile  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.main import app  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

# --------------------------------------------------------------------------
# 4) SQLite In-Memory Engine + Session
# --------------------------------------------------------------------------
SQLALCHEMY_TEST_URL = "sqlite:///:memory:"

engine_test = create_engine(
    SQLALCHEMY_TEST_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


# SQLite braucht explizites PRAGMA für Foreign Keys
@event.listens_for(engine_test, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestingSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine_test
)


# --------------------------------------------------------------------------
# 5) Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_socket_emit():
    """Mock emit_to_household_sync global, damit kein Event-Loop nötig ist."""
    with patch("app.socket_manager.emit_to_household_sync") as mock_emit:
        # Auch in den Routern patchen, da dort der Import direkt ist
        with patch("app.routers.budgets.emit_to_household_sync", mock_emit):
            with patch("app.routers.recurring_bills.emit_to_household_sync", mock_emit):
                with patch("app.routers.shopping.emit_to_household_sync", mock_emit):
                    with patch("app.routers.todos.emit_to_household_sync", mock_emit):
                        with patch("app.routers.expenses.emit_to_household_sync", mock_emit):
                            with patch("app.routers.settlements.emit_to_household_sync", mock_emit):
                                with patch("app.routers.chores.emit_to_household_sync", mock_emit):
                                    with patch("app.routers.households.emit_to_household_sync", mock_emit):
                                        with patch("app.routers.events.emit_to_household_sync", mock_emit):
                                            with patch("app.routers.polls.emit_to_household_sync", mock_emit):
                                                with patch("app.routers.pets.emit_to_household_sync", mock_emit):
                                                    with patch("app.routers.food.emit_to_household_sync", mock_emit):
                                                        with patch("app.routers.notes.emit_to_household_sync", mock_emit):
                                                            with patch("app.routers.calendars.emit_to_household_sync", mock_emit):
                                                                with patch("app.routers.files.emit_to_household_sync", mock_emit):
                                                                    yield mock_emit


@pytest.fixture()
def db():
    """Erstellt alle Tabellen, liefert eine frische Session, räumt danach auf."""
    Base.metadata.create_all(bind=engine_test)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine_test)


@pytest.fixture()
def client(db):
    """FastAPI TestClient mit überschriebener DB-Dependency."""

    def _override_get_db():
        try:
            yield db
        finally:
            pass  # Session wird in db-Fixture geschlossen

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# --- Households ---


@pytest.fixture()
def household_a(db) -> Household:
    h = Household(
        id=uuid.uuid4(),
        name="Haushalt Alpha",
        invite_code="ALPHA123",
        currency="CHF",
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


@pytest.fixture()
def household_b(db) -> Household:
    h = Household(
        id=uuid.uuid4(),
        name="Haushalt Beta",
        invite_code="BETA456",
        currency="CHF",
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    return h


# --- Users ---


@pytest.fixture()
def user_a(db, household_a) -> User:
    user = User(
        id=uuid.uuid4(),
        email="alice@example.com",
        password_hash=hash_password("password123"),
        display_name="Alice",
    )
    db.add(user)
    db.flush()

    membership = HouseholdMember(
        id=uuid.uuid4(),
        household_id=household_a.id,
        user_id=user.id,
        role="admin",
    )
    db.add(membership)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def user_b(db, household_b) -> User:
    user = User(
        id=uuid.uuid4(),
        email="bob@example.com",
        password_hash=hash_password("password456"),
        display_name="Bob",
    )
    db.add(user)
    db.flush()

    membership = HouseholdMember(
        id=uuid.uuid4(),
        household_id=household_b.id,
        user_id=user.id,
        role="admin",
    )
    db.add(membership)
    db.commit()
    db.refresh(user)
    return user


# --- Tokens ---


@pytest.fixture()
def token_a(user_a) -> str:
    return create_access_token(str(user_a.id))


@pytest.fixture()
def token_b(user_b) -> str:
    return create_access_token(str(user_b.id))


# --- Shopping Lists ---


@pytest.fixture()
def shopping_list_a(db, household_a) -> ShoppingList:
    lst = ShoppingList(
        id=uuid.uuid4(),
        household_id=household_a.id,
        name="Lebensmittel",
        position=0,
    )
    db.add(lst)
    db.commit()
    db.refresh(lst)
    return lst


@pytest.fixture()
def shopping_list_b(db, household_b) -> ShoppingList:
    lst = ShoppingList(
        id=uuid.uuid4(),
        household_id=household_b.id,
        name="Drogerie",
        position=0,
    )
    db.add(lst)
    db.commit()
    db.refresh(lst)
    return lst


# --- Shopping Items ---


@pytest.fixture()
def shopping_item_a(db, household_a, user_a, shopping_list_a) -> ShoppingItem:
    item = ShoppingItem(
        id=uuid.uuid4(),
        household_id=household_a.id,
        list_id=shopping_list_a.id,
        name="Milch",
        quantity="1L",
        added_by_user_id=user_a.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture()
def shopping_item_b(db, household_b, user_b, shopping_list_b) -> ShoppingItem:
    item = ShoppingItem(
        id=uuid.uuid4(),
        household_id=household_b.id,
        list_id=shopping_list_b.id,
        name="Brot",
        quantity="1 Stk",
        added_by_user_id=user_b.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


# --- Todos ---


@pytest.fixture()
def todo_a(db, household_a, user_a) -> Todo:
    todo = Todo(
        id=uuid.uuid4(),
        household_id=household_a.id,
        title="Küche putzen",
        created_by_user_id=user_a.id,
    )
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return todo


# --- Users (additional) ---


@pytest.fixture()
def user_a2(db, household_a) -> User:
    user = User(
        id=uuid.uuid4(),
        email="alice2@example.com",
        password_hash=hash_password("password789"),
        display_name="Alice2",
    )
    db.add(user)
    db.flush()
    membership = HouseholdMember(
        id=uuid.uuid4(),
        household_id=household_a.id,
        user_id=user.id,
        role="member",
    )
    db.add(membership)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def token_a2(user_a2) -> str:
    return create_access_token(str(user_a2.id))


# --- Expenses ---


@pytest.fixture()
def expense_a(db, household_a, user_a, user_a2) -> Expense:
    expense = Expense(
        id=uuid.uuid4(),
        household_id=household_a.id,
        description="Pizza",
        amount_rappen=3000,
        paid_by_user_id=user_a.id,
        expense_date=__import__("datetime").date.today(),
        split_type="even",
    )
    db.add(expense)
    db.flush()
    # Even split: 1500 + 1500
    for uid, amt in [(user_a.id, 1500), (user_a2.id, 1500)]:
        share = ExpenseShare(
            id=uuid.uuid4(),
            expense_id=expense.id,
            household_id=household_a.id,
            user_id=uid,
            amount_rappen=amt,
        )
        db.add(share)
    db.commit()
    db.refresh(expense)
    return expense


@pytest.fixture()
def expense_b(db, household_b, user_b) -> Expense:
    expense = Expense(
        id=uuid.uuid4(),
        household_id=household_b.id,
        description="Taxi",
        amount_rappen=2500,
        paid_by_user_id=user_b.id,
        expense_date=__import__("datetime").date.today(),
        split_type="even",
    )
    db.add(expense)
    db.flush()
    share = ExpenseShare(
        id=uuid.uuid4(),
        expense_id=expense.id,
        household_id=household_b.id,
        user_id=user_b.id,
        amount_rappen=2500,
    )
    db.add(share)
    db.commit()
    db.refresh(expense)
    return expense


@pytest.fixture()
def todo_b(db, household_b, user_b) -> Todo:
    todo = Todo(
        id=uuid.uuid4(),
        household_id=household_b.id,
        title="Einkaufen gehen",
        created_by_user_id=user_b.id,
    )
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return todo


# --- Budgets ---


@pytest.fixture()
def budget_a(db, household_a) -> Budget:
    from datetime import date
    b = Budget(
        id=uuid.uuid4(),
        household_id=household_a.id,
        month=date(2026, 8, 1),
        amount_rappen=500000,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


# --- RecurringBills ---


@pytest.fixture()
def bill_a(db, household_a) -> RecurringBill:
    b = RecurringBill(
        id=uuid.uuid4(),
        household_id=household_a.id,
        name="Miete",
        amount_rappen=150000,
        day_of_month=1,
        category="housing",
        split_type="even",
        active=True,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


@pytest.fixture()
def bill_b(db, household_b) -> RecurringBill:
    b = RecurringBill(
        id=uuid.uuid4(),
        household_id=household_b.id,
        name="Internet",
        amount_rappen=5000,
        day_of_month=15,
        category="housing",
        split_type="even",
        active=True,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


# --- Calendars ---


@pytest.fixture()
def calendar_a(db, household_a) -> Calendar:
    cal = Calendar(
        household_id=household_a.id,
        name="Allgemein",
        color="#5B8DEF",
        position=0,
    )
    db.add(cal)
    db.commit()
    db.refresh(cal)
    return cal


@pytest.fixture()
def calendar_b(db, household_b) -> Calendar:
    cal = Calendar(
        household_id=household_b.id,
        name="Allgemein",
        color="#5B8DEF",
        position=0,
    )
    db.add(cal)
    db.commit()
    db.refresh(cal)
    return cal


# --- Events ---


@pytest.fixture()
def event_a(db, household_a, user_a, calendar_a) -> Event:
    from datetime import datetime, timezone as tz
    e = Event(
        id=uuid.uuid4(),
        household_id=household_a.id,
        calendar_id=calendar_a.id,
        title="Team-Meeting",
        starts_at=datetime(2026, 8, 7, 10, 0, tzinfo=tz.utc),
        all_day=False,
        participant_ids=[],
        created_by_user_id=user_a.id,
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


@pytest.fixture()
def event_b(db, household_b, user_b, calendar_b) -> Event:
    from datetime import datetime, timezone as tz
    e = Event(
        id=uuid.uuid4(),
        household_id=household_b.id,
        calendar_id=calendar_b.id,
        title="Geburtstagsfeier",
        starts_at=datetime(2026, 8, 10, 18, 0, tzinfo=tz.utc),
        all_day=False,
        participant_ids=[],
        created_by_user_id=user_b.id,
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


@pytest.fixture()
def poll_a(db, household_a, user_a) -> EventPoll:
    p = EventPoll(
        id=uuid.uuid4(),
        household_id=household_a.id,
        question="Wann treffen wir uns?",
        status="offen",
        created_by_user_id=user_a.id,
    )
    db.add(p)
    db.flush()
    opt1 = EventPollOption(id=uuid.uuid4(), poll_id=p.id, household_id=household_a.id, label="Montag 18:00")
    opt2 = EventPollOption(id=uuid.uuid4(), poll_id=p.id, household_id=household_a.id, label="Dienstag 19:00")
    db.add_all([opt1, opt2])
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture()
def poll_b(db, household_b, user_b) -> EventPoll:
    p = EventPoll(
        id=uuid.uuid4(),
        household_id=household_b.id,
        question="Welches Restaurant?",
        status="offen",
        created_by_user_id=user_b.id,
    )
    db.add(p)
    db.flush()
    opt1 = EventPollOption(id=uuid.uuid4(), poll_id=p.id, household_id=household_b.id, label="Italienisch")
    opt2 = EventPollOption(id=uuid.uuid4(), poll_id=p.id, household_id=household_b.id, label="Japanisch")
    db.add_all([opt1, opt2])
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture()
def inactive_bill_a(db, household_a) -> RecurringBill:
    b = RecurringBill(
        id=uuid.uuid4(),
        household_id=household_a.id,
        name="Altes Abo",
        amount_rappen=2000,
        day_of_month=10,
        active=False,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


# --- Pets ---


@pytest.fixture()
def pet_a(db, household_a) -> Pet:
    pet = Pet(
        id=uuid.uuid4(),
        household_id=household_a.id,
        name="Luna",
        species="cat",
        breed="Europäisch Kurzhaar",
    )
    db.add(pet)
    db.commit()
    db.refresh(pet)
    return pet


# --- Medications ---


@pytest.fixture()
def medication_a(db, household_a, pet_a) -> Medication:
    med = Medication(
        id=uuid.uuid4(),
        household_id=household_a.id,
        pet_id=pet_a.id,
        name="Entwurmung",
        dosage="1 Tablette",
        schedule="Alle 3 Monate",
        active=True,
    )
    db.add(med)
    db.commit()
    db.refresh(med)
    return med


@pytest.fixture()
def medication_b(db, household_b, pet_b) -> Medication:
    med = Medication(
        id=uuid.uuid4(),
        household_id=household_b.id,
        pet_id=pet_b.id,
        name="Augentropfen",
        dosage="2 Tropfen",
        schedule="Täglich",
        active=True,
    )
    db.add(med)
    db.commit()
    db.refresh(med)
    return med


@pytest.fixture()
def pet_b(db, household_b) -> Pet:
    pet = Pet(
        id=uuid.uuid4(),
        household_id=household_b.id,
        name="Felix",
        species="cat",
    )
    db.add(pet)
    db.commit()
    db.refresh(pet)
    return pet


# --- Stored Files ---


@pytest.fixture()
def stored_file_a(db, household_a, user_a) -> StoredFile:
    sf = StoredFile(
        id=uuid.uuid4(),
        household_id=household_a.id,
        original_name="cat.jpg",
        mime_type="image/jpeg",
        size_bytes=12345,
        storage_path=f"{household_a.id}/test-cat.jpeg",
        uploaded_by_user_id=user_a.id,
    )
    db.add(sf)
    db.commit()
    db.refresh(sf)
    return sf


@pytest.fixture()
def stored_file_b(db, household_b, user_b) -> StoredFile:
    sf = StoredFile(
        id=uuid.uuid4(),
        household_id=household_b.id,
        original_name="dog.jpg",
        mime_type="image/jpeg",
        size_bytes=54321,
        storage_path=f"{household_b.id}/test-dog.jpeg",
        uploaded_by_user_id=user_b.id,
    )
    db.add(sf)
    db.commit()
    db.refresh(sf)
    return sf


# --- Recipes ---


@pytest.fixture()
def recipe_a(db, household_a) -> Recipe:
    r = Recipe(
        id=uuid.uuid4(),
        household_id=household_a.id,
        name="Spaghetti Bolognese",
        servings=4,
        cost_rappen=1500,
        duration_min=30,
        ingredients=["Spaghetti", "Hackfleisch", "Tomaten", "Zwiebeln"],
        is_favorite=True,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@pytest.fixture()
def recipe_b(db, household_b) -> Recipe:
    r = Recipe(
        id=uuid.uuid4(),
        household_id=household_b.id,
        name="Caesar Salad",
        servings=2,
        ingredients=["Romana-Salat", "Parmesan", "Croutons"],
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


@pytest.fixture()
def meal_plan_entry_a(db, household_a, recipe_a) -> MealPlanEntry:
    from datetime import date
    entry = MealPlanEntry(
        id=uuid.uuid4(),
        household_id=household_a.id,
        date=date(2026, 8, 10),  # ein Montag
        recipe_id=recipe_a.id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


# --- Notes ---


@pytest.fixture()
def note_a(db, household_a, user_a) -> Note:
    note = Note(
        id=uuid.uuid4(),
        household_id=household_a.id,
        title="Einkaufsliste Ideen",
        body="Milch, Brot, Käse",
        created_by_user_id=user_a.id,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@pytest.fixture()
def note_b(db, household_b, user_b) -> Note:
    note = Note(
        id=uuid.uuid4(),
        household_id=household_b.id,
        title="Urlaubsplanung",
        body="Flüge vergleichen",
        created_by_user_id=user_b.id,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@pytest.fixture()
def meal_plan_entry_b(db, household_b, recipe_b) -> MealPlanEntry:
    from datetime import date
    entry = MealPlanEntry(
        id=uuid.uuid4(),
        household_id=household_b.id,
        date=date(2026, 8, 10),
        recipe_id=recipe_b.id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


# --- Todo Reminders ---


@pytest.fixture()
def reminder_a(db, household_a, todo_a) -> TodoReminder:
    from datetime import datetime, timezone, timedelta
    reminder = TodoReminder(
        id=uuid.uuid4(),
        household_id=household_a.id,
        todo_id=todo_a.id,
        remind_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder


@pytest.fixture()
def reminder_b(db, household_b, todo_b) -> TodoReminder:
    from datetime import datetime, timezone, timedelta
    reminder = TodoReminder(
        id=uuid.uuid4(),
        household_id=household_b.id,
        todo_id=todo_b.id,
        remind_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder
