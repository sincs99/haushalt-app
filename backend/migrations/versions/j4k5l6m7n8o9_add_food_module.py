"""add_food_module

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-08-07 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'j4k5l6m7n8o9'
down_revision: Union[str, Sequence[str], None] = 'i3j4k5l6m7n8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create recipes and meal_plan_entries tables."""
    op.create_table(
        'recipes',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('household_id', UUID(as_uuid=True), sa.ForeignKey('households.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('servings', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('cost_rappen', sa.Integer(), nullable=True),
        sa.Column('duration_min', sa.Integer(), nullable=True),
        sa.Column('ingredients', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('is_favorite', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_recipes_household', 'recipes', ['household_id'])

    op.create_table(
        'meal_plan_entries',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('household_id', UUID(as_uuid=True), sa.ForeignKey('households.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('recipe_id', UUID(as_uuid=True), sa.ForeignKey('recipes.id', ondelete='SET NULL'), nullable=True),
        sa.Column('free_text', sa.String(150), nullable=True),
        sa.UniqueConstraint('household_id', 'date', name='uq_meal_plan_household_date'),
    )
    op.create_index('ix_meal_plan_household_date', 'meal_plan_entries', ['household_id', 'date'])


def downgrade() -> None:
    """Drop meal_plan_entries and recipes tables."""
    op.drop_index('ix_meal_plan_household_date', table_name='meal_plan_entries')
    op.drop_table('meal_plan_entries')
    op.drop_index('ix_recipes_household', table_name='recipes')
    op.drop_table('recipes')
