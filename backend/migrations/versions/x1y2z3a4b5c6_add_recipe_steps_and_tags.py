"""add_recipe_steps_and_tags

Zubereitungsschritte und Tags für Rezepte. Der KI-Assistent liefert beides,
die Rezept-Ansicht zeigt und speichert es; bestehende Rezepte erhalten leere Listen.

Revision ID: x1y2z3a4b5c6
Revises: w1x2y3z4a5b6
Create Date: 2026-10-06 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'x1y2z3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'w1x2y3z4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('recipes', sa.Column('steps', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('recipes', sa.Column('tags', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('recipes', 'tags')
    op.drop_column('recipes', 'steps')
