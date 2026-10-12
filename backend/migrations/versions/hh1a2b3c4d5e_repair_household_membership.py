"""repair_household_membership

Datenreparatur (CASA-10 / PD-H3): Vor der Haushaltssperre konnten parallele
Austritte zwei Altlasten hinterlassen:

1. Haushalte mit 0 Mitgliedern — samt allen Daten, beitretbar für jeden mit dem
   alten Einladungscode. Sie werden gelöscht (CASCADE auf alle Haushaltsdaten).
   Die hochgeladenen Dateien (``UPLOAD_DIR/<household_id>/``) entfernt der
   periodische Cleanup (app/services/file_cleanup.py), weil eine Migration das
   Dateisystem des App-Containers nicht kennt.
2. Haushalte mit Mitgliedern, aber ohne Admin — niemand konnte mehr verwalten.
   Das dienstälteste Mitglied (``joined_at``, dann ``user_id``) wird Admin, wie
   es die App seither bei jeder Mitgliedschaftsänderung tut
   (app/services/membership.py: ``ensure_admin``).

Revision ID: hh1a2b3c4d5e
Revises: fin1a2b3c4d5
Create Date: 2026-10-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'hh1a2b3c4d5e'
down_revision: Union[str, Sequence[str], None] = 'fin1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        DELETE FROM households h
        WHERE NOT EXISTS (
            SELECT 1 FROM household_members m WHERE m.household_id = h.id
        )
        """
    )
    op.execute(
        """
        UPDATE household_members SET role = 'admin'
        WHERE id IN (
            SELECT DISTINCT ON (m.household_id) m.id
            FROM household_members m
            WHERE NOT EXISTS (
                SELECT 1 FROM household_members a
                WHERE a.household_id = m.household_id AND a.role = 'admin'
            )
            ORDER BY m.household_id, m.joined_at ASC NULLS LAST, CAST(m.user_id AS TEXT) ASC
        )
        """
    )


def downgrade() -> None:
    """Downgrade schema.

    Reine Datenreparatur, nicht umkehrbar (gelöschte verwaiste Haushalte kommen nicht
    zurück, und "kein Admin" ist kein Zustand, den man wiederherstellen will).
    """
