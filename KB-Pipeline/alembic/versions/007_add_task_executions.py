"""Add task_executions table to track Celery task execution history with logs.

Revision ID: 007
Revises: 006
Create Date: 2026-05-29 00:00:00.000000

Tracks crawl/process/embed job execution with structured logs and result summaries.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '007'
down_revision = ('006', '9d14d2974166')
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'task_executions',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('task_name', sa.String(255), nullable=False),
        sa.Column('source_code', sa.String(50), nullable=True),
        sa.Column('status', postgresql.ENUM('pending', 'started', 'success', 'failed', 'retry', name='task_status'), nullable=False, server_default='pending'),
        sa.Column('started_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('logs', postgresql.JSON(), nullable=False, server_default='[]'),
        sa.Column('result_summary', postgresql.JSON(), nullable=False, server_default='{}'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_index('ix_task_executions_task_name', 'task_executions', ['task_name'])
    op.create_index('ix_task_executions_source', 'task_executions', ['source_code'])
    op.create_index('ix_task_executions_status', 'task_executions', ['status'])
    op.create_index('ix_task_executions_created', 'task_executions', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_task_executions_created', table_name='task_executions')
    op.drop_index('ix_task_executions_status', table_name='task_executions')
    op.drop_index('ix_task_executions_source', table_name='task_executions')
    op.drop_index('ix_task_executions_task_name', table_name='task_executions')
    op.drop_table('task_executions')
    op.execute("DROP TYPE IF EXISTS task_status;")
