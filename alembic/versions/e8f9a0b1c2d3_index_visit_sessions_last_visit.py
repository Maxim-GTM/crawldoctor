"""index visit_sessions (last_visit) and (country)

73f8498762a0 creates both with CREATE INDEX IF NOT EXISTS, and the model declares them, but the
production database (moved from Railway) has neither. Without the last_visit index, the
sessions list (ORDER BY last_visit DESC LIMIT 50) is a parallel seq scan and sort of 2.3M rows,
about 1 s per page. Built CONCURRENTLY so tracking writes keep flowing during the boot migration.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-10-28

"""
from alembic import op
import sqlalchemy as sa


revision = 'e8f9a0b1c2d3'
down_revision = 'd7e8f9a0b1c2'
branch_labels = None
depends_on = None

_INDEXES = {
    "ix_visit_sessions_last_visit": "visit_sessions (last_visit)",
    "ix_visit_sessions_country": "visit_sessions (country)",
}


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, target in _INDEXES.items():
            # An interrupted CONCURRENTLY build leaves an INVALID index behind, which IF NOT
            # EXISTS would then keep forever. Drop it so the build below starts over.
            invalid = op.get_bind().execute(
                sa.text(
                    "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                    "WHERE c.relname = :name AND NOT i.indisvalid"
                ),
                {"name": name},
            ).scalar()
            if invalid:
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {target}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name in reversed(list(_INDEXES)):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
