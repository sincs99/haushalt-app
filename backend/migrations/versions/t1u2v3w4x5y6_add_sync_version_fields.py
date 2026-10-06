"""add_sync_version_fields

updated_at + version für Offline-Sync (docs/offline-first-phase2.md, B2/B3)
auf shopping_lists, shopping_items, todos, chore_assignments.

Revision ID: t1u2v3w4x5y6
Revises: s1t2u3v4w5x6
Create Date: 2026-10-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 't1u2v3w4x5y6'
down_revision: Union[str, Sequence[str], None] = 's1t2u3v4w5x6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = ('shopping_lists', 'shopping_items', 'todos', 'chore_assignments')


def upgrade() -> None:
    """Upgrade schema."""
    for table in TABLES:
        op.add_column(
            table,
            sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        )
        # Erst nullable anlegen, mit created_at befüllen, dann NOT NULL setzen
        op.add_column(
            table,
            sa.Column(
                'updated_at',
                sa.DateTime(timezone=True),
                nullable=True,
                server_default=sa.func.now(),
            ),
        )
        op.execute(
            f"UPDATE {table} SET updated_at = COALESCE(created_at, now())"
        )
        op.alter_column(table, 'updated_at', nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    for table in reversed(TABLES):
        op.drop_column(table, 'updated_at')
        op.drop_column(table, 'version')
