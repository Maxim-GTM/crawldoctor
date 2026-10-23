"""Database checks the container entrypoint runs before starting the app.

    python3 -m app.db_bootstrap wait            # wait until the database accepts connections
    python3 -m app.db_bootstrap check-revision  # is the DB's alembic revision one this image knows?

Both connect with the full settings.database_url, so libpq parameters such as
sslmode=verify-full apply exactly as they do for the app.

check-revision exit codes (docker-entrypoint-single.sh branches on them):
    0  the DB is at a revision in alembic/versions (or has no alembic_version yet)
    3  the DB is at a revision this image does not know
    1  the check itself failed (connection or alembic error)
"""
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text

from app.config import settings

EXIT_UNKNOWN_REVISION = 3
_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def _describe(e: Exception) -> str:
    """One-line error description that never echoes the database URL (it holds the password)."""
    first_line = str(e).strip().splitlines()[0] if str(e).strip() else ""
    if "://" in first_line or "password" in first_line.lower():
        return type(e).__name__
    return f"{type(e).__name__}: {first_line}"


def _engine():
    return create_engine(settings.database_url, connect_args={"connect_timeout": 10})


def wait_for_db(max_attempts: int = 30, delay: float = 2.0) -> int:
    engine = _engine()
    try:
        for attempt in range(1, max_attempts + 1):
            try:
                with engine.connect() as conn:
                    conn.execute(text("SELECT 1"))
                print("✅ Database is ready!")
                return 0
            except Exception as e:
                print(f"⏳ Database not ready, waiting... (attempt {attempt}/{max_attempts}): {_describe(e)}")
                time.sleep(delay)
        print(f"❌ Could not connect to database after {max_attempts} attempts")
        return 1
    finally:
        engine.dispose()


def known_revisions() -> set:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(_ALEMBIC_INI)))
    return {rev.revision for rev in script.walk_revisions()}


def check_revision() -> int:
    from alembic.runtime.migration import MigrationContext

    engine = _engine()
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_heads()
    finally:
        engine.dispose()

    unknown = sorted(set(current) - known_revisions())
    if unknown:
        print(f"DB alembic revision(s) {', '.join(unknown)} not found in alembic/versions")
        return EXIT_UNKNOWN_REVISION
    print(f"DB alembic revision: {', '.join(current) or '(none)'}")
    return 0


def main(argv) -> int:
    commands = {"wait": wait_for_db, "check-revision": check_revision}
    if len(argv) != 2 or argv[1] not in commands:
        print(f"usage: python3 -m app.db_bootstrap {{{'|'.join(commands)}}}", file=sys.stderr)
        return 2
    try:
        return commands[argv[1]]()
    except Exception as e:
        print(f"❌ {argv[1]} failed: {_describe(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
