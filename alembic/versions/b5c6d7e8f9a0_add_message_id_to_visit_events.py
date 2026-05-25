"""add message_id to visit_events for MQ idempotency

Revision ID: b5c6d7e8f9a0
Revises: e3f4a5b6c7d8
Create Date: 2026-05-22

"""
from alembic import op
import sqlalchemy as sa


revision = 'b5c6d7e8f9a0'
down_revision = 'e3f4a5b6c7d8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'visit_events',
        sa.Column('message_id', sa.String(36), nullable=True)
    )
    op.create_index('ix_visit_events_message_id', 'visit_events', ['message_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_visit_events_message_id', table_name='visit_events')
    op.drop_column('visit_events', 'message_id')
