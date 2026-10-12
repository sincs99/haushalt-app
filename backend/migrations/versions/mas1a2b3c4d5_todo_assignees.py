"""todo_assignees: mehrere zuständige Personen pro Aufgabe

Bisher hatte eine Aufgabe höchstens eine zuständige Person
(``todos.assigned_to_user_id``). Neu: Zuordnungstabelle ``todo_assignees``
(PK ``todo_id, user_id`` — macht "Ich übernehme" race-sicher), keine Zeile =
offen für alle. Bestehende Zuweisungen werden übernommen, danach fällt die alte
Spalte weg.

Zusätzlich ``todos.done_by_user_id``: wer die Aufgabe abgehakt hat ("eine:r für
alle"). Bestehende erledigte Aufgaben bleiben ohne Angabe (unbekannt).

Downgrade: Spalte wiederherstellen, befüllt mit der zuerst eingetragenen Person
(weitere Zuständige gehen dabei verloren).

Revision ID: mas1a2b3c4d5
Revises: cal1a2b3c4d5
Create Date: 2026-10-11 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'mas1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'cal1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'todo_assignees',
        sa.Column('todo_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('household_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['todo_id'], ['todos.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['household_id'], ['households.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('todo_id', 'user_id'),
    )
    op.create_index('ix_todo_assignees_user_id', 'todo_assignees', ['user_id'])
    op.create_index(op.f('ix_todo_assignees_household_id'), 'todo_assignees', ['household_id'])

    # Bestehende Zuweisungen übernehmen (Zeitpunkt: Erstellung der Aufgabe)
    op.execute(
        "INSERT INTO todo_assignees (todo_id, user_id, household_id, created_at) "
        "SELECT id, assigned_to_user_id, household_id, COALESCE(created_at, now()) "
        "FROM todos WHERE assigned_to_user_id IS NOT NULL"
    )
    op.drop_column('todos', 'assigned_to_user_id')

    op.add_column('todos', sa.Column('done_by_user_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'todos_done_by_user_id_fkey', 'todos', 'users',
        ['done_by_user_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('todos_done_by_user_id_fkey', 'todos', type_='foreignkey')
    op.drop_column('todos', 'done_by_user_id')

    op.add_column('todos', sa.Column('assigned_to_user_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'todos_assigned_to_user_id_fkey', 'todos', 'users',
        ['assigned_to_user_id'], ['id'], ondelete='SET NULL'
    )
    # Erste zuständige Person (gleiche Reihenfolge wie das Modell)
    op.execute(
        "UPDATE todos SET assigned_to_user_id = ("
        "  SELECT a.user_id FROM todo_assignees a WHERE a.todo_id = todos.id"
        "  ORDER BY a.created_at, a.user_id LIMIT 1"
        ")"
    )
    op.drop_index(op.f('ix_todo_assignees_household_id'), table_name='todo_assignees')
    op.drop_index('ix_todo_assignees_user_id', table_name='todo_assignees')
    op.drop_table('todo_assignees')
