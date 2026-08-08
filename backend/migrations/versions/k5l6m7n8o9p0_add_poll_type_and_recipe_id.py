"""add poll_type and recipe_id

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# revision identifiers, used by Alembic.
revision = "k5l6m7n8o9p0"
down_revision = "j4k5l6m7n8o9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # EventPoll: poll_type Spalte
    op.add_column(
        "event_polls",
        sa.Column("poll_type", sa.String(10), nullable=False, server_default="event"),
    )
    # EventPoll: decided_meal_date Spalte
    op.add_column(
        "event_polls",
        sa.Column("decided_meal_date", sa.Date(), nullable=True),
    )
    # EventPollOption: recipe_id Spalte
    op.add_column(
        "event_poll_options",
        sa.Column("recipe_id", PG_UUID(as_uuid=True), nullable=True),
    )
    # FK für recipe_id
    op.create_foreign_key(
        "fk_poll_option_recipe",
        "event_poll_options",
        "recipes",
        ["recipe_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # CheckConstraint für poll_type
    op.create_check_constraint(
        "ck_poll_type",
        "event_polls",
        "poll_type IN ('event', 'meal')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_poll_type", "event_polls", type_="check")
    op.drop_constraint(
        "fk_poll_option_recipe", "event_poll_options", type_="foreignkey"
    )
    op.drop_column("event_poll_options", "recipe_id")
    op.drop_column("event_polls", "decided_meal_date")
    op.drop_column("event_polls", "poll_type")
