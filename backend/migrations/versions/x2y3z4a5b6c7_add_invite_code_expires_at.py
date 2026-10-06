"""add_invite_code_expires_at

Einladungscodes laufen ab (H-12). Neue Spalte households.invite_code_expires_at
(UTC, nullable; NULL = läuft nicht ab). Bestehende Haushalte erhalten beim
Upgrade 7 Tage ab Migrationszeitpunkt, damit alte Dauer-Codes nicht ewig
gültig bleiben; Admins können danach jederzeit einen neuen Code erzeugen.

Revision ID: x2y3z4a5b6c7
Revises: w1x2y3z4a5b6
Create Date: 2026-10-06 14:00:00.000000

"""
from datetime import datetime, timedelta, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'x2y3z4a5b6c7'
down_revision: Union[str, Sequence[str], None] = 'w1x2y3z4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'households',
        sa.Column('invite_code_expires_at', sa.DateTime(timezone=True), nullable=True),
    )
    households = sa.table(
        'households',
        sa.column('invite_code_expires_at', sa.DateTime(timezone=True)),
    )
    op.execute(
        households.update().values(
            invite_code_expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('households', 'invite_code_expires_at')
