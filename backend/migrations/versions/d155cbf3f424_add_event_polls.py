"""add_event_polls

Revision ID: d155cbf3f424
Revises: 4678310121c3
Create Date: 2026-08-07 20:49:48.196187

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd155cbf3f424'
down_revision: Union[str, Sequence[str], None] = '4678310121c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('event_polls',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('household_id', sa.UUID(), nullable=False),
    sa.Column('question', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='offen', nullable=False),
    sa.Column('created_by_user_id', sa.UUID(), nullable=False),
    sa.Column('decided_event_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status IN ('offen', 'entschieden')", name='ck_poll_status'),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['decided_event_id'], ['events.id'], ),
    sa.ForeignKeyConstraint(['household_id'], ['households.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('event_poll_options',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('poll_id', sa.UUID(), nullable=False),
    sa.Column('household_id', sa.UUID(), nullable=False),
    sa.Column('label', sa.String(length=100), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['household_id'], ['households.id'], ),
    sa.ForeignKeyConstraint(['poll_id'], ['event_polls.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('event_poll_votes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('option_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('household_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['household_id'], ['households.id'], ),
    sa.ForeignKeyConstraint(['option_id'], ['event_poll_options.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('option_id', 'user_id', name='uq_poll_vote_option_user')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('event_poll_votes')
    op.drop_table('event_poll_options')
    op.drop_table('event_polls')
