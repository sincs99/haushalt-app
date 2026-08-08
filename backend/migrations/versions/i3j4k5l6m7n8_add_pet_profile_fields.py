"""add_pet_profile_fields

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2026-08-07 22:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'i3j4k5l6m7n8'
down_revision: Union[str, Sequence[str], None] = 'h2i3j4k5l6m7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add pet profile fields (Slice 3)."""
    op.add_column('pets', sa.Column('chip_number', sa.String(50), nullable=True))
    op.add_column('pets', sa.Column('insurance', sa.String(100), nullable=True))
    op.add_column('pets', sa.Column('vet_name', sa.String(100), nullable=True))
    op.add_column('pets', sa.Column('food_notes', sa.String(500), nullable=True))
    op.add_column('pets', sa.Column('health_entries', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove pet profile fields."""
    op.drop_column('pets', 'health_entries')
    op.drop_column('pets', 'food_notes')
    op.drop_column('pets', 'vet_name')
    op.drop_column('pets', 'insurance')
    op.drop_column('pets', 'chip_number')
