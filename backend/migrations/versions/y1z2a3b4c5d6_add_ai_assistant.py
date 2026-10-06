"""add_ai_assistant

Opt-in pro Haushalt (households.ai_enabled, Standard false) und Tageszähler
ai_usage (Aufrufe, Input-/Output-Tokens) für das Tageslimit des KI-Assistenten.

Revision ID: y1z2a3b4c5d6
Revises: c8d9e0f1a2b3
Create Date: 2026-10-06 18:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'y1z2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'c8d9e0f1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'households',
        sa.Column('ai_enabled', sa.Boolean(), nullable=False, server_default='false'),
    )
    op.create_table(
        'ai_usage',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'household_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('households.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('calls', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.UniqueConstraint('household_id', 'day', name='uq_ai_usage_household_day'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('ai_usage')
    op.drop_column('households', 'ai_enabled')
