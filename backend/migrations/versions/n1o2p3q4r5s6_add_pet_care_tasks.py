"""add_pet_care_tasks

Revision ID: n1o2p3q4r5s6
Revises: m7n8o9p0q1r2
Create Date: 2026-08-10 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'n1o2p3q4r5s6'
down_revision: Union[str, Sequence[str], None] = 'm7n8o9p0q1r2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'pet_care_tasks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('household_id', sa.UUID(), nullable=False),
        sa.Column('pet_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('interval_days', sa.Integer(), nullable=False),
        sa.Column('next_due_at', sa.Date(), nullable=False),
        sa.Column('last_done_at', sa.Date(), nullable=True),
        sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pet_id'], ['pets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_pet_care_tasks_household_due',
        'pet_care_tasks',
        ['household_id', 'next_due_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_pet_care_tasks_household_due', table_name='pet_care_tasks')
    op.drop_table('pet_care_tasks')
