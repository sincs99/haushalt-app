"""add_todo_reminders

Revision ID: o1p2q3r4s5t6
Revises: n1o2p3q4r5s6
Create Date: 2026-08-10 10:28:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'o1p2q3r4s5t6'
down_revision: Union[str, Sequence[str], None] = 'n1o2p3q4r5s6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('todo_reminders',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('household_id', sa.UUID(), nullable=False),
        sa.Column('todo_id', sa.UUID(), nullable=False),
        sa.Column('remind_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['todo_id'], ['todos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_todo_reminders_household_remind', 'todo_reminders', ['household_id', 'remind_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_todo_reminders_household_remind', table_name='todo_reminders')
    op.drop_table('todo_reminders')
