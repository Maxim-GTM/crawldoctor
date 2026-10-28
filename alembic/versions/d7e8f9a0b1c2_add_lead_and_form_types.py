"""add lead_type / form_types to lead_summaries and form_type to journey_form_fills

Production is stamped with this revision, which was applied from a local checkout and never
committed (around 2026-08-26, when production's only lead_type values were written). Without
the file every boot logged "unknown revision" and skipped all migrations. This recreates its
schema, with existence checks, so the production chain is whole again and fresh databases
match production. Recovered from production's information_schema and pg_indexes on 2026-10-28:
these are the only columns production has that the committed migrations don't create.

Revision ID: d7e8f9a0b1c2
Revises: b5c6d7e8f9a0
Create Date: 2026-08-26

"""
from alembic import op
import sqlalchemy as sa


revision = 'd7e8f9a0b1c2'
down_revision = 'b5c6d7e8f9a0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    lead_columns = {col['name'] for col in inspector.get_columns('lead_summaries')}
    if 'lead_type' not in lead_columns:
        op.add_column('lead_summaries', sa.Column('lead_type', sa.String(length=50), nullable=True))
    if 'form_types' not in lead_columns:
        op.add_column('lead_summaries', sa.Column('form_types', sa.String(length=500), nullable=True))

    fill_columns = {col['name'] for col in inspector.get_columns('journey_form_fills')}
    if 'form_type' not in fill_columns:
        op.add_column('journey_form_fills', sa.Column('form_type', sa.String(length=50), nullable=True))

    # Both tables hold a few thousand rows: a plain CREATE INDEX is instant.
    op.execute("CREATE INDEX IF NOT EXISTS ix_lead_summaries_lead_type ON lead_summaries (lead_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_journey_form_fills_form_type ON journey_form_fills (form_type)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_journey_form_fills_form_type")
    op.execute("DROP INDEX IF EXISTS ix_lead_summaries_lead_type")
    op.drop_column('journey_form_fills', 'form_type')
    op.drop_column('lead_summaries', 'form_types')
    op.drop_column('lead_summaries', 'lead_type')
