"""add_events_table

Revision ID: 4678310121c3
Revises: f1a2b3c4d5e6
Create Date: 2026-08-07 16:15:42.855006

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4678310121c3'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('household_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=150), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('all_day', sa.Boolean(), nullable=False),
    sa.Column('category', sa.String(length=50), server_default='sonstiges', nullable=False),
    sa.Column('participant_ids', sa.JSON(), nullable=False),
    sa.Column('note', sa.String(length=500), nullable=True),
    sa.Column('created_by_user_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("category IN ('arbeit','katzen','haushalt','freunde','geburtstage','essen','sonstiges')", name='ck_event_category_valid'),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_events_household_starts', 'events', ['household_id', 'starts_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_events_household_starts', table_name='events')
    op.drop_table('events')
