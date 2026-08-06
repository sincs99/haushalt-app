"""add settlements

Revision ID: b4c8e2f7a31d
Revises: a7b3e5d91c4f
Create Date: 2026-08-06 09:48:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4c8e2f7a31d'
down_revision: Union[str, Sequence[str], None] = 'a7b3e5d91c4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('settlements',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('household_id', sa.UUID(), nullable=False),
    sa.Column('from_user_id', sa.UUID(), nullable=False),
    sa.Column('to_user_id', sa.UUID(), nullable=False),
    sa.Column('amount_rappen', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), server_default='CHF', nullable=False),
    sa.Column('settled_date', sa.Date(), server_default=sa.text('CURRENT_DATE'), nullable=False),
    sa.Column('note', sa.String(length=200), nullable=True),
    sa.Column('created_by_user_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('amount_rappen > 0', name='ck_settlement_amount_positive'),
    sa.CheckConstraint('from_user_id != to_user_id', name='ck_settlement_distinct_users'),
    sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['from_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['to_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_settlements_household_date', 'settlements', ['household_id', 'settled_date'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_settlements_household_date', table_name='settlements')
    op.drop_table('settlements')
