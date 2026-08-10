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
    """Add ondelete='SET NULL' to notes.created_by_user_id FK."""
    op.drop_constraint("notes_created_by_user_id_fkey", "notes", type_="foreignkey")
    op.create_foreign_key(
        "notes_created_by_user_id_fkey",
        "notes",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Remove ondelete='SET NULL' from notes.created_by_user_id FK."""
    op.drop_constraint("notes_created_by_user_id_fkey", "notes", type_="foreignkey")
    op.create_foreign_key(
        "notes_created_by_user_id_fkey",
        "notes",
        "users",
        ["created_by_user_id"],
        ["id"],
    )
