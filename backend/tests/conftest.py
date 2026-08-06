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
from app.models import Household, User, HouseholdMember, ShoppingItem, Todo, Expense, ExpenseShare, Settlement, Chore, ChoreAssignment  # noqa: E402
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
        with patch("app.routers.shopping.emit_to_household_sync", mock_emit):
            with patch("app.routers.todos.emit_to_household_sync", mock_emit):
                with patch("app.routers.expenses.emit_to_household_sync", mock_emit):
                    with patch("app.routers.settlements.emit_to_household_sync", mock_emit):
                        with patch("app.routers.chores.emit_to_household_sync", mock_emit):
                            with patch("app.routers.households.emit_to_household_sync", mock_emit):
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


# --- Shopping Items ---


@pytest.fixture()
def shopping_item_a(db, household_a, user_a) -> ShoppingItem:
    item = ShoppingItem(
        id=uuid.uuid4(),
        household_id=household_a.id,
        name="Milch",
        quantity="1L",
        added_by_user_id=user_a.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.fixture()
def shopping_item_b(db, household_b, user_b) -> ShoppingItem:
    item = ShoppingItem(
        id=uuid.uuid4(),
        household_id=household_b.id,
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
