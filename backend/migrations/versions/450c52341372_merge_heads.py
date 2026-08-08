"""merge_heads

Revision ID: 450c52341372
Revises: a194489b8f0e, e8f4b2a6c9d3
Create Date: 2026-08-07 14:06:07.848146

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '450c52341372'
down_revision: Union[str, Sequence[str], None] = ('a194489b8f0e', 'e8f4b2a6c9d3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
