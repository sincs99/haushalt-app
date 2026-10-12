"""ledger_fk_restrict_ai_user_usage

Betrieb/Datenhygiene (CASA-55, PD-D1, PD-A2):

- Ledger-FKs auf ``users`` von CASCADE / SET NULL auf RESTRICT: ``expense_shares.user_id``,
  ``settlements.from_user_id``/``to_user_id``, ``expenses.paid_by_user_id``. Eine künftige
  Konto-Löschung muss die Person anonymisieren (siehe PROJECT-STATUS, „Konto-Löschung"),
  statt Buchungen still mitzulöschen und damit die Salden der anderen zu verändern.
- Neue Tabelle ``ai_user_usage``: Tageszähler der KI-Aufrufe pro Person (zusätzlich zum
  Haushaltslimit in ``ai_usage``).

Constraint-Namen sind explizit (gleiche Namen wie die PostgreSQL-Automatik), damit der
Downgrade sie wiederfindet (vgl. CASA-56, 0f34ff355756).

Revision ID: ops1a2b3c4d5
Revises: fnd1a2b3c4d5
Create Date: 2026-10-10 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ops1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'fnd1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (Tabelle, Spalte, ondelete vorher)
LEDGER_FKS = [
    ('expense_shares', 'user_id', 'CASCADE'),
    ('settlements', 'from_user_id', 'CASCADE'),
    ('settlements', 'to_user_id', 'CASCADE'),
    ('expenses', 'paid_by_user_id', 'SET NULL'),
]


def _replace_fk(table: str, column: str, ondelete: str) -> None:
    name = f'{table}_{column}_fkey'
    op.drop_constraint(name, table, type_='foreignkey')
    op.create_foreign_key(name, table, 'users', [column], ['id'], ondelete=ondelete)


def upgrade() -> None:
    """Upgrade schema."""
    for table, column, _old in LEDGER_FKS:
        _replace_fk(table, column, 'RESTRICT')

    op.create_table(
        'ai_user_usage',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('calls', sa.Integer(), nullable=False, server_default='0'),
        sa.UniqueConstraint('user_id', 'day', name='uq_ai_user_usage_user_day'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('ai_user_usage')
    for table, column, old in LEDGER_FKS:
        _replace_fk(table, column, old)
