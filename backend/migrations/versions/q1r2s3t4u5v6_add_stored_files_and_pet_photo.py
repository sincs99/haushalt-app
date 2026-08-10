"""add stored_files and pet photo_file_id

Revision ID: q1r2s3t4u5v6
Revises: p1q2r3s4t5u6
Create Date: 2026-08-10 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'q1r2s3t4u5v6'
down_revision: Union[str, Sequence[str], None] = 'p1q2r3s4t5u6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. stored_files Tabelle anlegen
    op.create_table(
        'stored_files',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('household_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('households.id', ondelete='CASCADE'), nullable=False),
        sa.Column('original_name', sa.String(255), nullable=False),
        sa.Column('mime_type', sa.String(100), nullable=False),
        sa.Column('size_bytes', sa.Integer, nullable=False),
        sa.Column('storage_path', sa.String(500), nullable=False),
        sa.Column('uploaded_by_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_index('ix_stored_files_household', 'stored_files', ['household_id'])

    # 2. pets.photo_file_id hinzufügen
    op.add_column('pets', sa.Column(
        'photo_file_id', postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.create_foreign_key(
        'fk_pets_photo_file_id', 'pets', 'stored_files',
        ['photo_file_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_pets_photo_file_id', 'pets', type_='foreignkey')
    op.drop_column('pets', 'photo_file_id')
    op.drop_index('ix_stored_files_household', table_name='stored_files')
    op.drop_table('stored_files')
