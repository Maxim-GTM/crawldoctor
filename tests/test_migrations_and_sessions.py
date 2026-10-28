"""The migration chain production depends on, and the sessions list query. No Postgres needed."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db_bootstrap import known_revisions
from app.models.visit import Visit, VisitSession
from app.services.analytics import AnalyticsService

# The revision production's alembic_version holds (checked 2026-10-28).
PRODUCTION_REVISION = "d7e8f9a0b1c2"
_SCRIPT = ScriptDirectory.from_config(Config(str(Path(__file__).resolve().parent.parent / "alembic.ini")))


def test_production_revision_is_known_so_boot_migrations_run():
    # docker-entrypoint-single.sh skips every migration while the DB revision is unknown.
    assert PRODUCTION_REVISION in known_revisions()


def test_single_head_reachable_from_production():
    heads = _SCRIPT.get_heads()
    assert len(heads) == 1
    upgrade_path = [rev.revision for rev in _SCRIPT.iterate_revisions(heads[0], PRODUCTION_REVISION)]
    assert "e8f9a0b1c2d3" in upgrade_path  # the sessions last_visit index runs on the next boot


def test_production_revision_follows_last_committed_one():
    assert _SCRIPT.get_revision(PRODUCTION_REVISION).down_revision == "b5c6d7e8f9a0"


def test_last_visit_index_is_built_concurrently():
    source = Path(_SCRIPT.get_revision("e8f9a0b1c2d3").path).read_text()
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS" in source
    assert "autocommit_block" in source
    assert "visit_sessions (last_visit)" in source


def test_list_sessions_orders_by_last_visit_and_counts_small_tables_exactly():
    engine = create_engine("sqlite://")
    VisitSession.__table__.create(engine)
    Visit.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for i in range(5):
        db.add(VisitSession(id=f"s{i}", ip_address="192.0.2.1", user_agent="ua",
                            first_visit=start, last_visit=start + timedelta(hours=i)))
    db.commit()

    result = AnalyticsService().list_sessions(db, limit=3, offset=0)

    assert [s["session_id"] for s in result["sessions"]] == ["s4", "s3", "s2"]
    assert result["total_count"] == 5
    assert result["has_next"] is True
    db.close()
    engine.dispose()
