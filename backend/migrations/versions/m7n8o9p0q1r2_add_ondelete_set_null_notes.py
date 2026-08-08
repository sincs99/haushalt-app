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
    with op.batch_alter_table("notes") as batch_op:
        batch_op.drop_constraint("fk_notes_created_by_user_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_notes_created_by_user_id",
            "users",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("notes") as batch_op:
        batch_op.drop_constraint("fk_notes_created_by_user_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_notes_created_by_user_id",
            "users",
            ["created_by_user_id"],
            ["id"],
        )
