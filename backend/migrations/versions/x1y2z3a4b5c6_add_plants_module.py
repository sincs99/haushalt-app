"""add plants module

Tabellen plants, plant_care_tasks, plant_care_logs (Epic 20: Pflanzen).

Revision ID: x1y2z3a4b5c6
Revises: x2y3z4a5b6c7
Create Date: 2026-10-06 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'x1y2z3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'x2y3z4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'plants',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('household_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('households.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('species', sa.String(80), nullable=True),
        sa.Column('location', sa.String(80), nullable=True),
        sa.Column('notes', sa.String(1000), nullable=True),
        sa.Column('care_notes', sa.String(2000), nullable=True),
        sa.Column('photo_file_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('stored_files.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_plants_household_id', 'plants', ['household_id'])

    op.create_table(
        'plant_care_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('household_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('households.id', ondelete='CASCADE'), nullable=False),
        sa.Column('plant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('plants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('care_type', sa.String(20), nullable=False),
        sa.Column('label', sa.String(100), nullable=True),
        sa.Column('interval_days', sa.Integer(), nullable=False),
        sa.Column('next_due_at', sa.Date(), nullable=False),
        sa.Column('last_done_at', sa.Date(), nullable=True),
        sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "care_type IN ('water', 'fertilize', 'repot', 'mist', 'other')",
            name='ck_plant_care_task_type',
        ),
    )
    op.create_index('ix_plant_care_tasks_household_due', 'plant_care_tasks',
                    ['household_id', 'next_due_at'])
    op.create_index('ix_plant_care_tasks_plant', 'plant_care_tasks', ['plant_id'])

    op.create_table(
        'plant_care_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('household_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('households.id', ondelete='CASCADE'), nullable=False),
        sa.Column('plant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('plants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('care_task_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('plant_care_tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('care_type', sa.String(20), nullable=False),
        sa.Column('label', sa.String(100), nullable=True),
        sa.Column('done_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('done_by_user_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('note', sa.String(500), nullable=True),
    )
    op.create_index('ix_plant_care_logs_household_id', 'plant_care_logs', ['household_id'])
    op.create_index('ix_plant_care_logs_plant_done', 'plant_care_logs', ['plant_id', 'done_at'])


def downgrade() -> None:
    op.drop_index('ix_plant_care_logs_plant_done', table_name='plant_care_logs')
    op.drop_index('ix_plant_care_logs_household_id', table_name='plant_care_logs')
    op.drop_table('plant_care_logs')
    op.drop_index('ix_plant_care_tasks_plant', table_name='plant_care_tasks')
    op.drop_index('ix_plant_care_tasks_household_due', table_name='plant_care_tasks')
    op.drop_table('plant_care_tasks')
    op.drop_index('ix_plants_household_id', table_name='plants')
    op.drop_table('plants')
