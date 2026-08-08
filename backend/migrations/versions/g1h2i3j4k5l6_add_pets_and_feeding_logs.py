"""add_pets_and_feeding_logs

Revision ID: g1h2i3j4k5l6
Revises: d155cbf3f424
Create Date: 2026-08-07 21:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g1h2i3j4k5l6'
down_revision: Union[str, Sequence[str], None] = 'd155cbf3f424'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1) pets Tabelle erstellen
    op.create_table(
        'pets',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('household_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('species', sa.String(length=30), nullable=False),
        sa.Column('breed', sa.String(length=80), nullable=True),
        sa.Column('birthdate', sa.Date(), nullable=True),
        sa.Column('weight_grams', sa.Integer(), nullable=True),
        sa.Column('photo_url', sa.String(length=500), nullable=True),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # 2) feeding_logs Tabelle erstellen
    op.create_table(
        'feeding_logs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('household_id', sa.UUID(), nullable=False),
        sa.Column('pet_id', sa.UUID(), nullable=False),
        sa.Column('slot', sa.String(length=10), nullable=False),
        sa.Column('fed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('fed_by_user_id', sa.UUID(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pet_id'], ['pets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['fed_by_user_id'], ['users.id']),
        sa.UniqueConstraint('pet_id', 'date', 'slot', name='uq_feeding_pet_date_slot'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_feeding_date', 'feeding_logs', ['date'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_feeding_date', table_name='feeding_logs')
    op.drop_table('feeding_logs')
    op.drop_table('pets')
