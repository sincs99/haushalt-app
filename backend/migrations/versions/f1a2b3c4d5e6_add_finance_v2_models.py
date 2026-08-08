"""add_finance_v2_models

Revision ID: f1a2b3c4d5e6
Revises: e6cbf2921e48
Create Date: 2026-08-07 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e6cbf2921e48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- budgets ---
    op.create_table(
        'budgets',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('household_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('month', sa.Date(), nullable=False),
        sa.Column('amount_rappen', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('household_id', 'month', name='uq_budget_household_month'),
        sa.CheckConstraint('amount_rappen > 0', name='ck_budget_amount_positive'),
    )

    # --- recurring_bills (VOR expenses FK, da referenziert) ---
    op.create_table(
        'recurring_bills',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('household_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('amount_rappen', sa.Integer(), nullable=False),
        sa.Column('day_of_month', sa.Integer(), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column(
            'split_type',
            sa.Enum('even', 'custom', name='expense_split_type', create_type=False),
            server_default='even',
            nullable=False,
        ),
        sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            'day_of_month >= 1 AND day_of_month <= 28', name='ck_bill_day_range'
        ),
        sa.CheckConstraint('amount_rappen > 0', name='ck_bill_amount_positive'),
    )

    # --- expenses: neue Spalten ---
    op.add_column('expenses', sa.Column('category', sa.String(length=50), nullable=True))
    op.add_column(
        'expenses',
        sa.Column('recurring_bill_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_expenses_recurring_bill_id',
        'expenses',
        'recurring_bills',
        ['recurring_bill_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    # --- expenses: Spalten entfernen ---
    op.drop_constraint('fk_expenses_recurring_bill_id', 'expenses', type_='foreignkey')
    op.drop_column('expenses', 'recurring_bill_id')
    op.drop_column('expenses', 'category')

    # --- Tabellen entfernen ---
    op.drop_table('recurring_bills')
    op.drop_table('budgets')
