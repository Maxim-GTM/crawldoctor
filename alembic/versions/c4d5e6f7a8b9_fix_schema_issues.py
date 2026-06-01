"""Fix is_bot default, add updated_at to visit_sessions, add FK on journey_form_fills.visit_event_id

Revision ID: f1a2b3c4d5e6
Revises: c4d5e6f7a8b9
Create Date: 2026-04-02

"""
from alembic import op
import sqlalchemy as sa


revision = 'f1a2b3c4d5e6'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fix is_bot default from TRUE to FALSE — new visits should not be assumed bots
    op.alter_column(
        'visits', 'is_bot',
        server_default=sa.text('false'),
    )

    # Add updated_at column to visit_sessions for audit/staleness tracking
    op.add_column(
        'visit_sessions',
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    )

    # Add FK with NOT VALID — enforces on new rows without scanning orphaned existing rows
    op.execute("""
        ALTER TABLE journey_form_fills
        ADD CONSTRAINT fk_journey_form_fills_visit_event_id
        FOREIGN KEY (visit_event_id) REFERENCES visit_events (id)
        ON DELETE SET NULL
        NOT VALID
    """)


def downgrade() -> None:
    op.drop_constraint('fk_journey_form_fills_visit_event_id', 'journey_form_fills', type_='foreignkey')
    op.drop_column('visit_sessions', 'updated_at')
    op.alter_column('visits', 'is_bot', server_default=sa.text('true'))
