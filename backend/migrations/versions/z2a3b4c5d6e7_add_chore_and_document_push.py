"""add_chore_and_document_push

Push-Erinnerungen für Putzplan ("Du bist dran") und Ablaufdaten von Dokumenten:
Merker, ob schon benachrichtigt wurde (wie todo_reminders/pet_care_tasks).

- chore_assignments.notified_at: "Du bist dran" am Fälligkeitstag verschickt
- documents.expiry_soon_notified_at: Vorwarnung (30 Tage vorher) verschickt
- documents.expiry_notified_at: Hinweis am Ablauftag verschickt

Revision ID: z2a3b4c5d6e7
Revises: y1z2a3b4c5d6
Create Date: 2026-10-06 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'z2a3b4c5d6e7'
down_revision: Union[str, Sequence[str], None] = 'y1z2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'chore_assignments',
        sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'documents',
        sa.Column('expiry_soon_notified_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'documents',
        sa.Column('expiry_notified_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('documents', 'expiry_notified_at')
    op.drop_column('documents', 'expiry_soon_notified_at')
    op.drop_column('chore_assignments', 'notified_at')
