"""add calendars, replace event category with calendar_id

Revision ID: p1q2r3s4t5u6
Revises: o1p2q3r4s5t6
Create Date: 2026-08-10 12:28:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'p1q2r3s4t5u6'
down_revision: Union[str, Sequence[str], None] = 'o1p2q3r4s5t6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Farbpalette für automatisch erstellte Kalender
PALETTE = ['#5B8DEF', '#F4A261', '#6E9273', '#9C6E79', '#E76F51', '#C09A62', '#8B8B8B']


def upgrade() -> None:
    """Dreistufige Migration: Schema → Daten → Schema finalisieren."""

    # ── Phase 1: Schema-Änderungen ──────────────────────────────────────
    # 1a. calendars-Tabelle anlegen
    op.create_table(
        'calendars',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('household_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('households.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(50), nullable=False),
        sa.Column('color', sa.String(7), nullable=False),
        sa.Column('position', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_calendars_household', 'calendars', ['household_id'])

    # 1b. events.calendar_id als NULLABLE hinzufügen (wird in Phase 3 NOT NULL)
    op.add_column('events', sa.Column(
        'calendar_id', postgresql.UUID(as_uuid=True), nullable=True
    ))
    op.create_foreign_key(
        'fk_events_calendar_id', 'events', 'calendars',
        ['calendar_id'], ['id'], ondelete='CASCADE'
    )

    # ── Phase 2: Datenmigration ─────────────────────────────────────────
    connection = op.get_bind()

    # Alle Haushalte holen
    households = connection.execute(
        sa.text("SELECT id FROM households")
    ).fetchall()

    for hh in households:
        hh_id = hh[0]

        # Einzigartige categories dieses Haushalts ermitteln
        cats = connection.execute(
            sa.text(
                "SELECT DISTINCT category FROM events "
                "WHERE household_id = :hid"
            ),
            {"hid": hh_id},
        ).fetchall()

        if not cats:
            # Haushalt ohne Events → Default-Kalender "Allgemein"
            connection.execute(
                sa.text(
                    "INSERT INTO calendars (id, household_id, name, color, position) "
                    "VALUES (gen_random_uuid(), :hid, 'Allgemein', '#5B8DEF', 0)"
                ),
                {"hid": hh_id},
            )
            continue

        for idx, (cat,) in enumerate(cats):
            cal_name = cat.capitalize() if cat else 'Sonstiges'
            cal_color = PALETTE[idx % len(PALETTE)]

            connection.execute(
                sa.text(
                    "INSERT INTO calendars (id, household_id, name, color, position) "
                    "VALUES (gen_random_uuid(), :hid, :name, :color, :pos)"
                ),
                {"hid": hh_id, "name": cal_name, "color": cal_color, "pos": idx},
            )

    # Backfill calendar_id: Matching über INITCAP(category) = calendar.name
    connection.execute(sa.text(
        "UPDATE events SET calendar_id = c.id "
        "FROM calendars c "
        "WHERE events.household_id = c.household_id "
        "AND INITCAP(events.category) = c.name"
    ))

    # Sonderfall: NULL/leere/unbekannte categories → Fallback-Kalender
    # (höchste position = zuletzt eingefügt, typischerweise "Sonstiges")
    connection.execute(sa.text(
        "UPDATE events SET calendar_id = ("
        "  SELECT c.id FROM calendars c "
        "  WHERE c.household_id = events.household_id "
        "  ORDER BY c.position DESC LIMIT 1"
        ") WHERE events.calendar_id IS NULL"
    ))

    # ── Phase 3: Schema finalisieren ────────────────────────────────────
    # 3a. calendar_id auf NOT NULL setzen
    op.alter_column('events', 'calendar_id', nullable=False)

    # 3b. Alte CheckConstraint entfernen
    op.drop_constraint('ck_event_category_valid', 'events', type_='check')

    # 3c. category-Spalte entfernen
    op.drop_column('events', 'category')


def downgrade() -> None:
    """Revert: calendar_id → category, calendars-Tabelle droppen."""
    connection = op.get_bind()

    # 1. category-Spalte wiederherstellen (nullable zunächst, default 'sonstiges')
    op.add_column('events', sa.Column(
        'category', sa.String(50), nullable=True, server_default='sonstiges'
    ))

    # 2. category aus Kalendername backfüllen (lowercase, best effort)
    connection.execute(sa.text(
        "UPDATE events SET category = LOWER(c.name) "
        "FROM calendars c WHERE events.calendar_id = c.id"
    ))

    # 3. category auf NOT NULL setzen
    op.alter_column('events', 'category', nullable=False, server_default='sonstiges')

    # 4. CheckConstraint wieder anlegen
    op.create_check_constraint(
        'ck_event_category_valid', 'events',
        "category IN ('arbeit','katzen','haushalt','freunde','geburtstage','essen','sonstiges')"
    )

    # 5. FK und Spalte calendar_id entfernen
    op.drop_constraint('fk_events_calendar_id', 'events', type_='foreignkey')
    op.drop_column('events', 'calendar_id')

    # 6. calendars-Tabelle droppen (Index wird mit Tabelle entfernt)
    op.drop_index('ix_calendars_household', 'calendars')
    op.drop_table('calendars')
