"""add_sensors

Raumklima: Sensoren mit letztem Stand, ausgedünnter Verlauf und ein
Schreib-Schlüssel pro Haushalt (gespeichert als SHA-256-Hash).

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-11-10 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, Sequence[str], None] = 'b4c5d6e7f8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'sensor_ingest_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'household_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('households.id', ondelete='CASCADE'),
            nullable=False,
            unique=True,
        ),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('token_prefix', sa.String(12), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        'sensor_devices',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'household_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('households.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('external_id', sa.String(100), nullable=False),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('room', sa.String(60), nullable=True),
        sa.Column('temperature', sa.Float(), nullable=True),
        sa.Column('humidity', sa.Float(), nullable=True),
        sa.Column('battery', sa.Float(), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_logged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('household_id', 'external_id', name='uq_sensor_device_household_external'),
    )
    op.create_index('ix_sensor_devices_household_id', 'sensor_devices', ['household_id'])
    op.create_table(
        'sensor_readings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'device_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('sensor_devices.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('temperature', sa.Float(), nullable=True),
        sa.Column('humidity', sa.Float(), nullable=True),
    )
    op.create_index('ix_sensor_readings_device_recorded', 'sensor_readings', ['device_id', 'recorded_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_sensor_readings_device_recorded', table_name='sensor_readings')
    op.drop_table('sensor_readings')
    op.drop_index('ix_sensor_devices_household_id', table_name='sensor_devices')
    op.drop_table('sensor_devices')
    op.drop_table('sensor_ingest_tokens')
