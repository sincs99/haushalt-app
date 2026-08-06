"""add split_type to expenses

Revision ID: a7b3e5d91c4f
Revises: 61637c8c98fb
Create Date: 2026-08-06 09:18:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b3e5d91c4f'
down_revision: Union[str, Sequence[str], None] = '61637c8c98fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Enum-Typ für PostgreSQL anlegen
    expense_split_type = sa.Enum("even", "custom", name="expense_split_type")
    expense_split_type.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "expenses",
        sa.Column(
            "split_type",
            sa.Enum("even", "custom", name="expense_split_type"),
            nullable=False,
            server_default="even",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("expenses", "split_type")
    # Enum-Typ entfernen
    sa.Enum(name="expense_split_type").drop(op.get_bind(), checkfirst=True)
