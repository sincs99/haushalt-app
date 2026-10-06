"""event times as household wall clock, recurring bill default payer

Revision ID: u1v2w3x4y5z6
Revises: s1t2u3v4w5x6
Create Date: 2026-10-06 10:00:00.000000

Termine wurden bisher ohne Offset gespeichert; Postgres (Session-Zeitzone UTC)
hat "09:00" damit als 09:00 UTC abgelegt, gemeint war 09:00 Haushaltszeit.
Die Daten werden einmalig umgedeutet: gespeicherte UTC-Wanduhrzeit → Wanduhrzeit
in der Zeitzone des Haushalts. Ausgenommen sind Termine aus entschiedenen
Abstimmungen — sie wurden mit dem korrekten Zeitpunkt (jetzt, UTC) angelegt.

Wiederkehrende Rechnungen bekommen einen Standard-Zahler (recurring_bills.paid_by_user_id);
ohne Zahler wird nicht mehr gebucht.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


# revision identifiers, used by Alembic.
revision: str = 'u1v2w3x4y5z6'
down_revision: Union[str, Sequence[str], None] = 's1t2u3v4w5x6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NOT_FROM_POLL = "e.id NOT IN (SELECT decided_event_id FROM event_polls WHERE decided_event_id IS NOT NULL)"


def upgrade() -> None:
    op.add_column(
        "recurring_bills",
        sa.Column(
            "paid_by_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL", name="fk_recurring_bills_paid_by_user_id"),
            nullable=True,
        ),
    )

    # (ts AT TIME ZONE 'UTC') → Wanduhrzeit, die als UTC gespeichert war;
    # (… AT TIME ZONE h.timezone) → dieselbe Wanduhrzeit in Haushaltszeit
    op.execute(f"""
        UPDATE events e SET
            starts_at = (e.starts_at AT TIME ZONE 'UTC') AT TIME ZONE h.timezone,
            ends_at = (e.ends_at AT TIME ZONE 'UTC') AT TIME ZONE h.timezone
        FROM households h
        WHERE e.household_id = h.id AND {_NOT_FROM_POLL}
    """)


def downgrade() -> None:
    op.drop_constraint("fk_recurring_bills_paid_by_user_id", "recurring_bills", type_="foreignkey")
    op.drop_column("recurring_bills", "paid_by_user_id")

    op.execute(f"""
        UPDATE events e SET
            starts_at = (e.starts_at AT TIME ZONE h.timezone) AT TIME ZONE 'UTC',
            ends_at = (e.ends_at AT TIME ZONE h.timezone) AT TIME ZONE 'UTC'
        FROM households h
        WHERE e.household_id = h.id AND {_NOT_FROM_POLL}
    """)
