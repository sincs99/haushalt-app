"""integrity: ondelete rules, unique vote/booking, household_id indexes

Revision ID: v1w2x3y4z5a6
Revises: u1v2w3x4y5z6
Create Date: 2026-10-06 12:00:00.000000

- Fremdschlüssel ohne ondelete: Löschen eines Termins aus einer entschiedenen
  Abstimmung und das Löschen eines Haushalts (letztes Mitglied tritt aus)
  scheiterten mit einer FK-Verletzung. Abgelaufene Refresh-Tokens, auf die ein
  älteres Token verweist, ließen sich nicht aufräumen.
- event_poll_votes.poll_id + UNIQUE(poll_id, user_id): eine Stimme pro Person und
  Abstimmung, auch bei gleichzeitigen Requests. Bestehende Mehrfachstimmen werden
  auf die jüngste reduziert.
- expenses.booked_month + UNIQUE(recurring_bill_id, booked_month): eine Buchung pro
  Rechnung und Monat. Bei bestehenden Doppelbuchungen zählt nur die erste als
  Buchung; die Ausgaben selbst bleiben erhalten.
- Indizes auf household_id für häufig gefilterte Tabellen.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


# revision identifiers, used by Alembic.
revision: str = 'v1w2x3y4z5a6'
down_revision: Union[str, Sequence[str], None] = 'u1v2w3x4y5z6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (Tabelle, Spalte, Zieltabelle, neues ondelete)
_FK_CHANGES = [
    ("household_members", "household_id", "households", "CASCADE"),
    ("event_polls", "household_id", "households", "CASCADE"),
    ("event_polls", "decided_event_id", "events", "SET NULL"),
    ("event_poll_options", "household_id", "households", "CASCADE"),
    ("event_poll_votes", "household_id", "households", "CASCADE"),
    ("refresh_tokens", "replaced_by_id", "refresh_tokens", "SET NULL"),
]

_HOUSEHOLD_INDEX_TABLES = [
    "chores", "event_polls", "feeding_logs", "medication_logs", "medications",
    "pets", "recurring_bills", "shopping_items", "todos",
]


def _set_fk(table: str, column: str, target: str, ondelete: str | None) -> None:
    name = f"{table}_{column}_fkey"  # Postgres-Standardname aus den ursprünglichen Migrationen
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(name, table, target, [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    for table, column, target, ondelete in _FK_CHANGES:
        _set_fk(table, column, target, ondelete)

    # --- Eine Stimme pro Person und Abstimmung ---
    op.add_column("event_poll_votes", sa.Column("poll_id", PG_UUID(as_uuid=True), nullable=True))
    op.execute("""
        UPDATE event_poll_votes v SET poll_id = o.poll_id
        FROM event_poll_options o WHERE v.option_id = o.id
    """)
    op.execute("""
        DELETE FROM event_poll_votes v
        USING event_poll_votes w
        WHERE v.poll_id = w.poll_id AND v.user_id = w.user_id
          AND (v.created_at, v.id) < (w.created_at, w.id)
    """)
    op.alter_column("event_poll_votes", "poll_id", nullable=False)
    op.create_foreign_key(
        "event_poll_votes_poll_id_fkey", "event_poll_votes", "event_polls",
        ["poll_id"], ["id"], ondelete="CASCADE",
    )
    op.create_unique_constraint("uq_poll_vote_poll_user", "event_poll_votes", ["poll_id", "user_id"])

    # --- Eine Buchung pro Rechnung und Monat ---
    op.add_column("expenses", sa.Column("booked_month", sa.Date(), nullable=True))
    op.execute("""
        UPDATE expenses e SET booked_month = date_trunc('month', e.expense_date)::date
        WHERE e.recurring_bill_id IS NOT NULL
          AND e.id = (
              SELECT x.id FROM expenses x
              WHERE x.recurring_bill_id = e.recurring_bill_id
                AND date_trunc('month', x.expense_date) = date_trunc('month', e.expense_date)
              ORDER BY x.created_at, x.id
              LIMIT 1
          )
    """)
    op.create_unique_constraint(
        "uq_expense_bill_booked_month", "expenses", ["recurring_bill_id", "booked_month"]
    )

    for table in _HOUSEHOLD_INDEX_TABLES:
        op.create_index(f"ix_{table}_household_id", table, ["household_id"])


def downgrade() -> None:
    for table in _HOUSEHOLD_INDEX_TABLES:
        op.drop_index(f"ix_{table}_household_id", table_name=table)

    op.drop_constraint("uq_expense_bill_booked_month", "expenses", type_="unique")
    op.drop_column("expenses", "booked_month")

    op.drop_constraint("uq_poll_vote_poll_user", "event_poll_votes", type_="unique")
    op.drop_constraint("event_poll_votes_poll_id_fkey", "event_poll_votes", type_="foreignkey")
    op.drop_column("event_poll_votes", "poll_id")

    for table, column, target, _ in _FK_CHANGES:
        _set_fk(table, column, target, None)
