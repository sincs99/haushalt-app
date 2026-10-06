"""add tags (NFC/QR)

Physische Tags (NFC-Chip oder QR-Sticker), die beim Scannen eine
Ein-Tipp-Aktion auslösen. Siehe app/services/tag_actions.py.

Revision ID: x1y2z3a4b5c6
Revises: w1x2y3z4a5b6
Create Date: 2026-10-06 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


# revision identifiers, used by Alembic.
revision: str = 'x1y2z3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'w1x2y3z4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "household_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(30), nullable=False),
        # Polymorph (Tier, Ämtli, Todo …) → kein Fremdschlüssel
        sa.Column("target_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column(
            "created_by_user_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_table("tags")
