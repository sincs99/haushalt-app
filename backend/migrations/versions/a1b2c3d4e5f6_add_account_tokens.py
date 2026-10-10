"""add_account_tokens

Konto-Funktionen: E-Mail-Verifizierung, Passwort zurücksetzen, Konto löschen.

- users.email_verified_at: Adresse per Link bestätigt
- users.deleted_at: Konto anonymisiert (Login gesperrt, Zeile bleibt für Verweise)
- user_tokens: Einmal-Tokens (Hash) für Passwort-Reset und E-Mail-Bestätigung

Revision ID: a1b2c3d4e5f6
Revises: a3b4c5d6e7f8
Create Date: 2026-10-09 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        'user_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('purpose', sa.String(length=32), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_tokens_user_purpose', 'user_tokens', ['user_id', 'purpose'])
    op.create_index('ix_user_tokens_token_hash', 'user_tokens', ['token_hash'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_user_tokens_token_hash', table_name='user_tokens')
    op.drop_index('ix_user_tokens_user_purpose', table_name='user_tokens')
    op.drop_table('user_tokens')
    op.drop_column('users', 'deleted_at')
    op.drop_column('users', 'email_verified_at')
