"""repair_json_nulls_and_created_at

Datenreparatur (P0-3 / CASA-04): Explizites ``null`` in PATCH-Requests konnte in
NOT-NULL-JSON-Spalten das JSON-Literal ``null`` speichern (erfüllt NOT NULL, bricht
aber alle Lesepfade — z. B. GET /events bzw. /recipes für den ganzen Haushalt).
Solche Werte werden auf ``[]`` gesetzt. Die API lehnt ``null`` inzwischen ab
(app/core/patch_schema.py) und die Modelle schreiben ``None`` als SQL-NULL.

Schema-Drift (CASA-56, Teil): ``created_at`` (und ``budgets.updated_at``) sind in den
Modellen NOT NULL, in der DB aber nullable. Fehlende Werte werden mit ``now()``
aufgefüllt und die Spalten auf NOT NULL gesetzt — der Drift-Check der pg-Lane
(tests/pg/test_pg_smoke.py) prüft danach auch die Nullability.

Revision ID: fnd1a2b3c4d5
Revises: a3b4c5d6e7f8
Create Date: 2026-10-10 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'fnd1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (Tabelle, Spalte) — NOT-NULL-JSON-Listen, die kein JSON-null enthalten dürfen
JSON_LIST_COLUMNS = [
    ('events', 'participant_ids'),
    ('recipes', 'ingredients'),
    ('recipes', 'steps'),
    ('recipes', 'tags'),
    ('todos', 'tags'),
    ('chores', 'rotation_order'),
]

# (Tabelle, Spalte) — im Modell NOT NULL, in der DB bisher nullable
TIMESTAMP_COLUMNS = [
    ('budgets', 'created_at'),
    ('budgets', 'updated_at'),
    ('calendars', 'created_at'),
    ('pet_care_tasks', 'created_at'),
    ('plant_care_tasks', 'created_at'),
    ('plants', 'created_at'),
    ('recurring_bills', 'created_at'),
    ('stored_files', 'created_at'),
    ('widget_tokens', 'created_at'),
]


def upgrade() -> None:
    """Upgrade schema."""
    for table, column in JSON_LIST_COLUMNS:
        op.execute(
            f"UPDATE {table} SET {column} = '[]' WHERE CAST({column} AS TEXT) = 'null'"
        )

    for table, column in TIMESTAMP_COLUMNS:
        op.execute(f"UPDATE {table} SET {column} = now() WHERE {column} IS NULL")
        op.alter_column(table, column, nullable=False)


def downgrade() -> None:
    """Downgrade schema.

    Die JSON-Reparatur ist nicht umkehrbar (und muss es nicht sein: ``[]`` ist für
    alle Lesepfade gültig). Nur die NOT-NULL-Constraints werden zurückgenommen.
    """
    for table, column in TIMESTAMP_COLUMNS:
        op.alter_column(table, column, nullable=True)
