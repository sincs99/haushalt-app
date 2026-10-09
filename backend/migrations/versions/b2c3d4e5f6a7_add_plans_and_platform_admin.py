"""add_plans_and_platform_admin

Tarife/Abrechnung und Plattform-Admin:

- users.is_active, users.is_platform_admin, users.terms_accepted_at, users.terms_version
- households.plan, households.plan_expires_at, households.stripe_customer_id
- subscriptions: Abos pro Haushalt und Anbieter (stripe/apple/google/manual)
- billing_events: verarbeitete Webhook-Ereignisse (Idempotenz)

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('users', sa.Column('is_platform_admin', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('terms_accepted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('terms_version', sa.String(length=20), nullable=True))

    op.add_column('households', sa.Column('plan', sa.String(length=20), nullable=False, server_default='free'))
    op.add_column('households', sa.Column('plan_expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('households', sa.Column('stripe_customer_id', sa.String(length=64), nullable=True))
    op.create_unique_constraint('uq_households_stripe_customer_id', 'households', ['stripe_customer_id'])

    op.create_table(
        'subscriptions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('household_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('provider', sa.String(length=16), nullable=False),
        sa.Column('provider_subscription_id', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('note', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'provider_subscription_id', name='uq_subscriptions_provider_id'),
    )
    op.create_index('ix_subscriptions_household_id', 'subscriptions', ['household_id'])

    op.create_table(
        'billing_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('provider', sa.String(length=16), nullable=False),
        sa.Column('event_id', sa.String(length=128), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'event_id', name='uq_billing_events_provider_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('billing_events')
    op.drop_index('ix_subscriptions_household_id', table_name='subscriptions')
    op.drop_table('subscriptions')
    op.drop_constraint('uq_households_stripe_customer_id', 'households', type_='unique')
    op.drop_column('households', 'stripe_customer_id')
    op.drop_column('households', 'plan_expires_at')
    op.drop_column('households', 'plan')
    op.drop_column('users', 'terms_version')
    op.drop_column('users', 'terms_accepted_at')
    op.drop_column('users', 'is_platform_admin')
    op.drop_column('users', 'is_active')
