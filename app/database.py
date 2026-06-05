"""Database configuration and session management."""
from datetime import date, timedelta
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from sqlalchemy import create_engine, event, MetaData, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from typing import Generator
import structlog
from fastapi import HTTPException

from app.config import settings

logger = structlog.get_logger()


def _make_async_url(sync_url: str) -> tuple:
    """Convert a psycopg2/libpq URL to asyncpg format, extracting SSL settings."""
    p = urlparse(sync_url)
    params = {k: v[0] for k, v in parse_qs(p.query).items()}
    sslmode = params.pop("sslmode", None)
    connect_args = {"connect_timeout": 30}
    if sslmode in ("require", "verify-ca", "verify-full"):
        connect_args["ssl"] = True
    scheme = p.scheme
    if scheme in ("postgresql", "postgres"):
        scheme = "postgresql+asyncpg"
    else:
        scheme = scheme.replace("psycopg2", "asyncpg")
    new_query = urlencode(params) if params else ""
    return urlunparse(p._replace(scheme=scheme, query=new_query)), connect_args


# ---------------------------------------------------------------------------
# Sync engine — used by analytics, auth, admin, and background jobs
# ---------------------------------------------------------------------------
engine = create_engine(
    settings.database_url,
    poolclass=QueuePool,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,
    pool_recycle=7200,
    pool_timeout=settings.database_pool_timeout,
    echo=settings.debug,
    connect_args={
        "connect_timeout": 30,
    },
    execution_options={
        "isolation_level": "READ COMMITTED"
    }
)

# Set statement_timeout after connect rather than as a startup parameter,
# since Neon's connection pooler rejects it in the startup packet.
@event.listens_for(engine, "connect")
def _set_statement_timeout(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute(f"SET statement_timeout = {settings.database_statement_timeout}")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Async engine — used by the tracking service and MQ consumer
# ---------------------------------------------------------------------------
_async_url, _async_connect_args = _make_async_url(settings.database_url)

async_engine = create_async_engine(
    _async_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,
    pool_recycle=7200,
    pool_timeout=settings.database_pool_timeout,
    echo=settings.debug,
    connect_args=_async_connect_args,
    execution_options={
        "isolation_level": "READ COMMITTED"
    },
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ---------------------------------------------------------------------------
# Base / metadata
# ---------------------------------------------------------------------------
Base = declarative_base()
metadata = MetaData()


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------
def get_db() -> Generator[Session, None, None]:
    """Sync session dependency — used by analytics, auth, and admin routes."""
    db = SessionLocal()
    try:
        yield db
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Database session error",
            error=str(e) or repr(e),
            error_type=type(e).__name__,
            error_args=str(e.args) if hasattr(e, 'args') else None,
        )
        db.rollback()
        raise
    finally:
        db.close()


async def get_async_db():
    """Async session dependency — used by the tracking route and MQ consumer."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Async database session error", error=str(e))
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------
async def init_db():
    """Initialize database tables."""
    try:
        Base.metadata.create_all(bind=engine)
        ensure_event_partitions()
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error("Failed to create database tables", error=str(e))
        raise


def ensure_event_partitions() -> None:
    """Ensure visit_events is partitioned and recent partitions exist."""
    try:
        with engine.begin() as conn:
            relkind = conn.execute(
                text("SELECT relkind FROM pg_class WHERE relname = 'visit_events'")
            ).scalar()

            if not relkind:
                logger.info("visit_events table doesn't exist yet, will be created by SQLAlchemy")
                return

            if relkind == 'r':
                logger.info("visit_events is a regular table, not partitioned (this is fine for now)")
                return

            if relkind == 'p':
                logger.info("visit_events is partitioned, ensuring partitions exist")

                try:
                    conn.execute(text("CREATE TABLE IF NOT EXISTS visit_events_default PARTITION OF visit_events DEFAULT"))
                except Exception as exc:
                    logger.debug("Default partition already exists or failed", error=str(exc))

                today = date.today()
                start = today - timedelta(days=settings.event_partition_days_back)
                end = today + timedelta(days=settings.event_partition_days_ahead)

                current = start
                while current <= end:
                    next_day = current + timedelta(days=1)
                    partition_name = f"visit_events_{current.strftime('%Y%m%d')}"
                    try:
                        conn.execute(
                            text(
                                f"CREATE TABLE IF NOT EXISTS {partition_name} "
                                f"PARTITION OF visit_events FOR VALUES FROM ('{current}') TO ('{next_day}')"
                            )
                        )
                    except Exception:
                        pass
                    current = next_day

                logger.info("Event partitions ensured successfully")
    except Exception as exc:
        logger.warning("Could not ensure event partitions (this is non-critical)", error=str(exc))


async def close_db():
    """Close all database connections."""
    try:
        engine.dispose()
        await async_engine.dispose()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error("Error closing database connections", error=str(e))
