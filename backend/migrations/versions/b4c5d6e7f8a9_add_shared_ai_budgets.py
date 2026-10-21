"""Add the global AI budget and idempotent call reservations.

Revision ID: b4c5d6e7f8a9
Revises: b2c3d4e5f6a7
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b4c5d6e7f8a9"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_budget_counters",
        sa.Column("scope_key", sa.String(48), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("scope_key", "day"),
    )
    op.create_table(
        "ai_call_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("household_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("state", sa.String(12), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_call_reservations_day", "ai_call_reservations", ["day"])
    # Preserve existing account counters without modification. Both older
    # tables describe the same dispatches, so do not add their totals together.
    # Their larger daily total retains history after household/account deletion.
    op.execute(sa.text(
        "INSERT INTO ai_budget_counters (scope_key, day, calls) "
        "SELECT 'global', day, MAX(calls) FROM ("
        "SELECT day, SUM(calls) AS calls FROM ai_usage GROUP BY day "
        "UNION ALL SELECT day, SUM(calls) AS calls FROM ai_user_usage GROUP BY day"
        ") AS prior_usage GROUP BY day"
    ))


def downgrade() -> None:
    op.drop_index("ix_ai_call_reservations_day", table_name="ai_call_reservations")
    op.drop_table("ai_call_reservations")
    op.drop_table("ai_budget_counters")
