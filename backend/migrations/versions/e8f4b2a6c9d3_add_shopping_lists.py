"""add shopping lists

Revision ID: e8f4b2a6c9d3
Revises: d5f2a8e3b7c1
Create Date: 2026-08-07 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8f4b2a6c9d3'
down_revision: Union[str, Sequence[str], None] = 'd5f2a8e3b7c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema – 3-Phasen-Strategie für sichere Datenmigration."""

    # ── Phase 1: Schema-Erweiterung (nullable) ─────────────────────────
    # 1a) Neue Tabelle shopping_lists
    op.create_table(
        'shopping_lists',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('household_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('icon', sa.String(length=50), nullable=True),
        sa.Column('position', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_shopping_lists_household', 'shopping_lists', ['household_id'], unique=False)

    # 1b) shopping_items um neue Spalten erweitern (list_id zunächst nullable!)
    op.add_column(
        'shopping_items',
        sa.Column('list_id', sa.UUID(), nullable=True),
    )
    op.add_column(
        'shopping_items',
        sa.Column('store', sa.String(length=100), nullable=True),
    )
    op.add_column(
        'shopping_items',
        sa.Column('assigned_to_user_id', sa.UUID(), nullable=True),
    )

    # Foreign Keys für die neuen Spalten
    op.create_foreign_key(
        'fk_shopping_items_list_id',
        'shopping_items', 'shopping_lists',
        ['list_id'], ['id'],
        ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_shopping_items_assigned_to_user_id',
        'shopping_items', 'users',
        ['assigned_to_user_id'], ['id'],
        ondelete='SET NULL',
    )

    # Index auf list_id für performante Abfragen nach Liste
    op.create_index('ix_shopping_items_list', 'shopping_items', ['list_id'], unique=False)

    # ── Phase 2: Datenmigration (Raw SQL, kein ORM) ────────────────────
    # 2a) Für jeden Haushalt mit existierenden shopping_items eine
    #     Default-Liste "Lebensmittel" erstellen
    op.execute(sa.text("""
        INSERT INTO shopping_lists (id, household_id, name, position, created_at)
        SELECT gen_random_uuid(), household_id, 'Lebensmittel', 0, NOW()
        FROM shopping_items
        GROUP BY household_id
    """))

    # 2b) Bestehende Items der jeweiligen Default-Liste zuordnen
    op.execute(sa.text("""
        UPDATE shopping_items si
        SET list_id = sl.id
        FROM shopping_lists sl
        WHERE si.household_id = sl.household_id
          AND si.list_id IS NULL
    """))

    # ── Phase 3: NOT NULL erzwingen ────────────────────────────────────
    # Jetzt sind alle bestehenden Zeilen migriert → Constraint aktivieren
    op.alter_column(
        'shopping_items',
        'list_id',
        existing_type=sa.UUID(),
        nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema – Spalten und Tabelle entfernen."""
    # 1) NOT NULL rückgängig machen (für sauberes Löschen)
    op.alter_column(
        'shopping_items',
        'list_id',
        existing_type=sa.UUID(),
        nullable=True,
    )

    # 2) Indices entfernen
    op.drop_index('ix_shopping_items_list', table_name='shopping_items')

    # 3) Foreign Keys entfernen
    op.drop_constraint('fk_shopping_items_assigned_to_user_id', 'shopping_items', type_='foreignkey')
    op.drop_constraint('fk_shopping_items_list_id', 'shopping_items', type_='foreignkey')

    # 4) Neue Spalten von shopping_items entfernen
    op.drop_column('shopping_items', 'assigned_to_user_id')
    op.drop_column('shopping_items', 'store')
    op.drop_column('shopping_items', 'list_id')

    # 5) shopping_lists Tabelle und Index entfernen
    op.drop_index('ix_shopping_lists_household', table_name='shopping_lists')
    op.drop_table('shopping_lists')
