import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean, String, DateTime, ForeignKey, Enum, UniqueConstraint,
    Integer, CheckConstraint, Index, Date, text, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Household(Base):
    __tablename__ = "households"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    invite_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    timezone: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="Europe/Zurich"
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="CHF"
    )

    members: Mapped[list["HouseholdMember"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    shopping_items: Mapped[list["ShoppingItem"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    todos: Mapped[list["Todo"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    expenses: Mapped[list["Expense"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    settlements: Mapped[list["Settlement"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    chores: Mapped[list["Chore"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    chore_assignments: Mapped[list["ChoreAssignment"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    shopping_lists: Mapped[list["ShoppingList"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    budgets: Mapped[list["Budget"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    recurring_bills: Mapped[list["RecurringBill"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    events: Mapped[list["Event"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    event_polls: Mapped[list["EventPoll"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    pets: Mapped[list["Pet"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    feeding_logs: Mapped[list["FeedingLog"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    medications: Mapped[list["Medication"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    medication_logs: Mapped[list["MedicationLog"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    recipes: Mapped[list["Recipe"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    meal_plan_entries: Mapped[list["MealPlanEntry"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )
    notes: Mapped[list["Note"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    memberships: Mapped[list["HouseholdMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class HouseholdMember(Base):
    __tablename__ = "household_members"
    __table_args__ = (
        UniqueConstraint("household_id", "user_id", name="uq_household_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        Enum("admin", "member", name="member_role"), default="member", nullable=False
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    household: Mapped["Household"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")


class ShoppingList(Base):
    __tablename__ = "shopping_lists"
    __table_args__ = (
        Index("ix_shopping_lists_household", "household_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    household: Mapped["Household"] = relationship(back_populates="shopping_lists")
    items: Mapped[list["ShoppingItem"]] = relationship(
        back_populates="shopping_list", cascade="all, delete-orphan"
    )


class ShoppingItem(Base):
    __tablename__ = "shopping_items"
    __table_args__ = (
        Index("ix_shopping_items_list", "list_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_checked: Mapped[bool] = mapped_column(default=False)
    added_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    list_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shopping_lists.id", ondelete="CASCADE"), nullable=False
    )
    store: Mapped[str | None] = mapped_column(String(100), nullable=True)
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    household: Mapped["Household"] = relationship(back_populates="shopping_items")
    shopping_list: Mapped["ShoppingList"] = relationship(back_populates="items")


class Todo(Base):
    __tablename__ = "todos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_done: Mapped[bool] = mapped_column(default=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    done_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, server_default="[]")

    household: Mapped["Household"] = relationship(back_populates="todos")


class Expense(Base):
    """Invariante: SUM(shares.amount_rappen) == expense.amount_rappen
    wird im Service-Layer erzwungen (Rundungslogik für Rappen-Verteilung bei ungeradem Split).
    """

    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint("amount_rappen > 0", name="ck_expense_amount_positive"),
        Index("ix_expenses_household_date", "household_id", "expense_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(String(200), nullable=False)
    amount_rappen: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="CHF"
    )
    split_type: Mapped[str] = mapped_column(
        Enum("even", "custom", name="expense_split_type"),
        nullable=False,
        server_default="even",
    )
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    paid_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    recurring_bill_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recurring_bills.id", ondelete="SET NULL"), nullable=True
    )
    expense_date: Mapped[datetime] = mapped_column(
        Date, nullable=False, server_default=text("CURRENT_DATE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    shares: Mapped[list["ExpenseShare"]] = relationship(
        back_populates="expense", cascade="all, delete-orphan", lazy="selectin"
    )
    household: Mapped["Household"] = relationship(back_populates="expenses")


class ExpenseShare(Base):
    __tablename__ = "expense_shares"
    __table_args__ = (
        CheckConstraint(
            "amount_rappen >= 0", name="ck_expense_share_amount_non_negative"
        ),
        UniqueConstraint("expense_id", "user_id", name="uq_expense_share_user"),
        Index("ix_expense_shares_household_user", "household_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    expense_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("expenses.id", ondelete="CASCADE"), nullable=False
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    amount_rappen: Mapped[int] = mapped_column(Integer, nullable=False)

    expense: Mapped["Expense"] = relationship(back_populates="shares")


class Settlement(Base):
    __tablename__ = "settlements"
    __table_args__ = (
        CheckConstraint("amount_rappen > 0", name="ck_settlement_amount_positive"),
        CheckConstraint("from_user_id != to_user_id", name="ck_settlement_distinct_users"),
        Index("ix_settlements_household_date", "household_id", "settled_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    from_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    to_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    amount_rappen: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="CHF"
    )
    settled_date: Mapped[datetime] = mapped_column(
        Date, nullable=False, server_default=text("CURRENT_DATE")
    )
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    household: Mapped["Household"] = relationship(back_populates="settlements")


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("household_id", "month", name="uq_budget_household_month"),
        CheckConstraint("amount_rappen > 0", name="ck_budget_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    month: Mapped[datetime] = mapped_column(Date, nullable=False)  # Immer 1. des Monats
    amount_rappen: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    household: Mapped["Household"] = relationship(back_populates="budgets")


class RecurringBill(Base):
    __tablename__ = "recurring_bills"
    __table_args__ = (
        CheckConstraint(
            "day_of_month >= 1 AND day_of_month <= 28", name="ck_bill_day_range"
        ),
        CheckConstraint("amount_rappen > 0", name="ck_bill_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    amount_rappen: Mapped[int] = mapped_column(Integer, nullable=False)
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    split_type: Mapped[str] = mapped_column(
        Enum("even", "custom", name="expense_split_type", create_type=False),
        nullable=False,
        server_default="even",
    )
    active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    household: Mapped["Household"] = relationship(back_populates="recurring_bills")


class Chore(Base):
    __tablename__ = "chores"
    __table_args__ = (
        CheckConstraint(
            "day_of_month >= 1 AND day_of_month <= 31",
            name="ck_chore_day_of_month_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recurrence: Mapped[str] = mapped_column(
        Enum("weekly", "biweekly", "monthly", name="chore_recurrence"),
        nullable=False,
    )
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    day_of_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rotation_order: Mapped[list] = mapped_column(JSON, nullable=False)
    next_rotation_index: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    anchor_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    household: Mapped["Household"] = relationship(back_populates="chores")
    assignments: Mapped[list["ChoreAssignment"]] = relationship(
        back_populates="chore", cascade="all, delete-orphan"
    )


class ChoreAssignment(Base):
    __tablename__ = "chore_assignments"
    __table_args__ = (
        UniqueConstraint("chore_id", "due_date", name="uq_chore_assignment_per_date"),
        Index("ix_chore_assignments_household_date", "household_id", "due_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    chore_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chores.id", ondelete="CASCADE"), nullable=False
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    due_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    household: Mapped["Household"] = relationship(back_populates="chore_assignments")
    chore: Mapped["Chore"] = relationship(back_populates="assignments")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(
            "category IN ('arbeit','katzen','haushalt','freunde','geburtstage','essen','sonstiges')",
            name="ck_event_category_valid",
        ),
        Index("ix_events_household_starts", "household_id", "starts_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="sonstiges"
    )
    participant_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    household: Mapped["Household"] = relationship(back_populates="events")


class EventPoll(Base):
    __tablename__ = "event_polls"
    __table_args__ = (
        CheckConstraint("status IN ('offen', 'entschieden')", name="ck_poll_status"),
        CheckConstraint("poll_type IN ('event', 'meal')", name="ck_poll_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id"), nullable=False
    )
    question: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="offen"
    )
    poll_type: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="event"
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    decided_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("events.id"), nullable=True
    )
    decided_meal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    options: Mapped[list["EventPollOption"]] = relationship(
        back_populates="poll", cascade="all, delete-orphan"
    )
    household: Mapped["Household"] = relationship(back_populates="event_polls")


class EventPollOption(Base):
    __tablename__ = "event_poll_options"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    poll_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event_polls.id", ondelete="CASCADE"), nullable=False
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    poll: Mapped["EventPoll"] = relationship(back_populates="options")
    votes: Mapped[list["EventPollVote"]] = relationship(
        back_populates="option", cascade="all, delete-orphan"
    )


class EventPollVote(Base):
    __tablename__ = "event_poll_votes"
    __table_args__ = (
        UniqueConstraint("option_id", "user_id", name="uq_poll_vote_option_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    option_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event_poll_options.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    option: Mapped["EventPollOption"] = relationship(back_populates="votes")


class Pet(Base):
    __tablename__ = "pets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    species: Mapped[str] = mapped_column(String(30), nullable=False, default="cat")
    breed: Mapped[str | None] = mapped_column(String(80), nullable=True)
    birthdate: Mapped[date | None] = mapped_column(Date, nullable=True)
    weight_grams: Mapped[int | None] = mapped_column(Integer, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Profil-Erweiterungen (Slice 3)
    chip_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    insurance: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vet_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    food_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    health_entries: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # health_entries Schema: [{"title": str, "subtitle": str, "severity": str}]
    # severity: "green" | "yellow" | "red"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    household: Mapped["Household"] = relationship(back_populates="pets")
    feeding_logs: Mapped[list["FeedingLog"]] = relationship(
        back_populates="pet", cascade="all, delete-orphan"
    )
    medications: Mapped[list["Medication"]] = relationship(
        back_populates="pet", cascade="all, delete-orphan"
    )


class FeedingLog(Base):
    __tablename__ = "feeding_logs"
    __table_args__ = (
        UniqueConstraint("pet_id", "date", "slot", name="uq_feeding_pet_date_slot"),
        Index("ix_feeding_date", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    pet_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pets.id", ondelete="CASCADE"), nullable=False
    )
    slot: Mapped[str] = mapped_column(String(10), nullable=False)
    fed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    fed_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)

    household: Mapped["Household"] = relationship(back_populates="feeding_logs")
    pet: Mapped["Pet"] = relationship(back_populates="feeding_logs")


class Medication(Base):
    __tablename__ = "medications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    pet_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pets.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    dosage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    schedule: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    household: Mapped["Household"] = relationship(back_populates="medications")
    pet: Mapped["Pet"] = relationship(back_populates="medications")
    logs: Mapped[list["MedicationLog"]] = relationship(
        back_populates="medication", cascade="all, delete-orphan"
    )


class MedicationLog(Base):
    __tablename__ = "medication_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    medication_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("medications.id", ondelete="CASCADE"), nullable=False
    )
    given_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    given_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    household: Mapped["Household"] = relationship(back_populates="medication_logs")
    medication: Mapped["Medication"] = relationship(back_populates="logs")


class Recipe(Base):
    __tablename__ = "recipes"
    __table_args__ = (
        Index("ix_recipes_household", "household_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    servings: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")
    cost_rappen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ingredients: Mapped[list] = mapped_column(JSON, nullable=False, server_default="[]")
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    household: Mapped["Household"] = relationship(back_populates="recipes")
    meal_plan_entries: Mapped[list["MealPlanEntry"]] = relationship(
        back_populates="recipe"
    )


class MealPlanEntry(Base):
    __tablename__ = "meal_plan_entries"
    __table_args__ = (
        UniqueConstraint("household_id", "date", name="uq_meal_plan_household_date"),
        Index("ix_meal_plan_household_date", "household_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True
    )
    free_text: Mapped[str | None] = mapped_column(String(150), nullable=True)

    household: Mapped["Household"] = relationship(back_populates="meal_plan_entries")
    recipe: Mapped["Recipe | None"] = relationship(
        back_populates="meal_plan_entries", lazy="selectin"
    )


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    tag: Mapped[str | None] = mapped_column(String(50), nullable=True)
    pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    household: Mapped["Household"] = relationship(back_populates="notes")
