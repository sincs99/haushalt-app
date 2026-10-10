"""pets_archived

Haustiere archivieren statt löschen (PD-P2 / CASA-15): ``pets.archived`` und
``pets.archived_at``. Archivierte Tiere behalten ihren Verlauf (Fütterungen,
Medikamentengaben, Pflegeaufgaben), erscheinen aber nicht mehr in Fütterung,
„Alle gefüttert“, Dashboard, Erinnerungen und Tag-Zielen (PD-P3).

Revision ID: pet1a2b3c4d5
Revises: hh1a2b3c4d5e
Create Date: 2026-10-10 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'pet1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'hh1a2b3c4d5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'pets',
        sa.Column('archived', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    op.add_column('pets', sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('pets', 'archived_at')
    op.drop_column('pets', 'archived')
