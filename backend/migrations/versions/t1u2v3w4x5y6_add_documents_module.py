"""add documents module

Revision ID: t1u2v3w4x5y6
Revises: v1w2x3y4z5a6
Create Date: 2026-10-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


# revision identifiers, used by Alembic.
revision: str = 't1u2v3w4x5y6'
down_revision: Union[str, Sequence[str], None] = 'v1w2x3y4z5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "household_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("households.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("category", sa.String(20), nullable=False, server_default="other"),
        sa.Column("notes", sa.String(2000), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
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
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "category IN ('contract', 'invoice', 'warranty', 'insurance', 'other')",
            name="ck_document_category",
        ),
    )
    op.create_index(
        "ix_documents_household_category", "documents", ["household_id", "category"]
    )

    # Seiten eines Dokuments (mehrseitige Scans); eine Datei gehört zu höchstens einem Dokument
    op.create_table(
        "document_files",
        sa.Column(
            "document_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "file_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("stored_files.id", ondelete="CASCADE"),
            primary_key=True,
            unique=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("document_files")
    op.drop_index("ix_documents_household_category", table_name="documents")
    op.drop_table("documents")
