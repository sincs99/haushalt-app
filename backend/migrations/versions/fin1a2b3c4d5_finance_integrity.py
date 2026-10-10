"""finance_integrity

Finanzen (CASA-01/02/03/08, PD-F1/F2/F5/F7):

- ``expenses.version`` für Optimistic Locking (If-Match → 409).
- ``expenses.created_by_user_id`` / ``updated_by_user_id`` / ``deleted_by_user_id`` /
  ``deleted_at``: Nachvollziehbarkeit und Soft Delete. ``settlements`` bekommt
  ``deleted_by_user_id`` / ``deleted_at`` (``created_by_user_id`` existiert schon).
- ``uq_expense_bill_booked_month`` wird vom Unique-Constraint zum partiellen Unique-Index
  ``WHERE deleted_at IS NULL``: eine gelöschte Buchung gibt den Monat frei, eine
  wiederhergestellte belegt ihn wieder (Wiederherstellen scheitert mit 409, wenn der
  Monat inzwischen neu gebucht wurde).
- PD-F5: ``recurring_bills.split_type = 'custom'`` hatte nie eine Wirkung (gebucht wurde
  immer gleichmässig) und wird von der API abgelehnt — Altbestand wird auf ``even`` gesetzt.

Revision ID: fin1a2b3c4d5
Revises: fnd1a2b3c4d5
Create Date: 2026-10-10 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'fin1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'fnd1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _user_fk_column(name: str) -> sa.Column:
    return sa.Column(
        name,
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "expenses",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("expenses", _user_fk_column("created_by_user_id"))
    op.add_column("expenses", _user_fk_column("updated_by_user_id"))
    op.add_column("expenses", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("expenses", _user_fk_column("deleted_by_user_id"))
    op.create_index(
        "ix_expenses_household_deleted", "expenses", ["household_id", "deleted_at"]
    )

    op.add_column("settlements", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("settlements", _user_fk_column("deleted_by_user_id"))

    op.drop_constraint("uq_expense_bill_booked_month", "expenses", type_="unique")
    op.create_index(
        "uq_expense_bill_booked_month",
        "expenses",
        ["recurring_bill_id", "booked_month"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.execute("UPDATE recurring_bills SET split_type = 'even' WHERE split_type = 'custom'")


def downgrade() -> None:
    """Downgrade schema.

    Soft-gelöschte Zeilen werden dabei endgültig gelöscht — ohne ``deleted_at`` würden
    sie sonst wieder in Salden und Budget zählen. ``split_type`` bleibt ``even``.
    """
    op.execute("DELETE FROM expenses WHERE deleted_at IS NOT NULL")
    op.execute("DELETE FROM settlements WHERE deleted_at IS NOT NULL")

    op.drop_index("uq_expense_bill_booked_month", table_name="expenses")
    op.create_unique_constraint(
        "uq_expense_bill_booked_month", "expenses", ["recurring_bill_id", "booked_month"]
    )

    op.drop_column("settlements", "deleted_by_user_id")
    op.drop_column("settlements", "deleted_at")

    op.drop_index("ix_expenses_household_deleted", table_name="expenses")
    op.drop_column("expenses", "deleted_by_user_id")
    op.drop_column("expenses", "deleted_at")
    op.drop_column("expenses", "updated_by_user_id")
    op.drop_column("expenses", "created_by_user_id")
    op.drop_column("expenses", "version")
