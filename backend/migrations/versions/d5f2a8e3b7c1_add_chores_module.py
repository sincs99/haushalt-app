"""add chores module

Revision ID: d5f2a8e3b7c1
Revises: b4c8e2f7a31d
Create Date: 2026-08-06 11:32:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd5f2a8e3b7c1'
down_revision: Union[str, Sequence[str], None] = 'b4c8e2f7a31d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1) timezone Spalte zu households hinzufügen
    op.add_column(
        "households",
        sa.Column("timezone", sa.String(length=50), server_default="Europe/Zurich", nullable=False),
    )

    # 2) Enum-Typ für PostgreSQL anlegen
    chore_recurrence = sa.Enum("weekly", "biweekly", "monthly", name="chore_recurrence")
    chore_recurrence.create(op.get_bind(), checkfirst=True)

    # 3) chores Tabelle erstellen
    op.create_table('chores',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('household_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=100), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('recurrence', postgresql.ENUM("weekly", "biweekly", "monthly", name="chore_recurrence", create_type=False), nullable=False),
        sa.Column('weekday', sa.Integer(), nullable=True),
        sa.Column('day_of_month', sa.Integer(), nullable=True),
        sa.Column('rotation_order', sa.JSON(), nullable=False),
        sa.Column('next_rotation_index', sa.Integer(), server_default='0', nullable=False),
        sa.Column('anchor_date', sa.Date(), nullable=False),
        sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by_user_id', sa.UUID(), nullable=True),
        sa.CheckConstraint('day_of_month >= 1 AND day_of_month <= 31', name='ck_chore_day_of_month_range'),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )

    # 4) chore_assignments Tabelle erstellen
    op.create_table('chore_assignments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('household_id', sa.UUID(), nullable=False),
        sa.Column('chore_id', sa.UUID(), nullable=False),
        sa.Column('assigned_user_id', sa.UUID(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_by_user_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['chore_id'], ['chores.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['assigned_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['completed_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('chore_id', 'due_date', name='uq_chore_assignment_per_date'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_chore_assignments_household_date', 'chore_assignments', ['household_id', 'due_date'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_chore_assignments_household_date', table_name='chore_assignments')
    op.drop_table('chore_assignments')
    op.drop_table('chores')
    # Enum-Typ entfernen
    sa.Enum(name="chore_recurrence").drop(op.get_bind(), checkfirst=True)
    op.drop_column("households", "timezone")
