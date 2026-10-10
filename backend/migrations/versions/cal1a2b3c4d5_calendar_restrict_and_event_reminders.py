"""calendar_restrict_and_event_reminders

CASA-20/54: ``events.calendar_id`` war ``ON DELETE CASCADE`` (plus ORM-Cascade) —
ein parallel bestätigter Termin verschwand mit dem gelöschten Kalender. Jetzt
``RESTRICT``: Ein Kalender mit Terminen lässt sich auf DB-Ebene nicht löschen.
Das Löschen eines ganzen Haushalts bleibt möglich (ORM löscht Termine vor Kalendern,
die DB-Cascades über ``household_id`` laufen in derselben Anweisung).

PD-K1: Termin-Erinnerungen — ``events.reminder`` (none|15m|1h|1d, Default none)
und ``events.notified_at`` (Claim des Push-Schedulers).

Revision ID: cal1a2b3c4d5
Revises: fnd1a2b3c4d5
Create Date: 2026-10-10 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'cal1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'fnd1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('fk_events_calendar_id', 'events', type_='foreignkey')
    op.create_foreign_key(
        'fk_events_calendar_id', 'events', 'calendars',
        ['calendar_id'], ['id'], ondelete='RESTRICT'
    )

    op.add_column('events', sa.Column(
        'reminder', sa.String(4), nullable=False, server_default='none'
    ))
    op.add_column('events', sa.Column(
        'notified_at', sa.DateTime(timezone=True), nullable=True
    ))
    op.create_check_constraint(
        'ck_events_reminder', 'events', "reminder IN ('none', '15m', '1h', '1d')"
    )


def downgrade() -> None:
    op.drop_constraint('ck_events_reminder', 'events', type_='check')
    op.drop_column('events', 'notified_at')
    op.drop_column('events', 'reminder')
    op.drop_constraint('fk_events_calendar_id', 'events', type_='foreignkey')
    op.create_foreign_key(
        'fk_events_calendar_id', 'events', 'calendars',
        ['calendar_id'], ['id'], ondelete='CASCADE'
    )
