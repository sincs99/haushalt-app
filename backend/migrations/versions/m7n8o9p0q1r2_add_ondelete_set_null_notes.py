"""add ondelete SET NULL to notes.created_by_user_id

Revision ID: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1
Create Date: 2026-08-08
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "m7n8o9p0q1r2"
down_revision = "l6m7n8o9p0q1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ondelete="SET NULL" is now included in the initial notes table creation
    # (migration l6m7n8o9p0q1). This migration is kept as a no-op for history.
    pass


def downgrade() -> None:
    pass
