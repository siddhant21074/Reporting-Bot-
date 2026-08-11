"""Database engine and session management.

One ``DATABASE_URL`` drives both supported backends:

    sqlite+aiosqlite:///storage/app.db                      local development
    postgresql+asyncpg://user:pass@host:5432/reportbot      production

Everything above this layer is backend-agnostic, so a laptop running SQLite and
a Droplet running Postgres execute the same code.
"""

import logging
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger("app.db")


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _normalise_url(url: str) -> str:
    """Upgrades a sync driver URL to its async equivalent.

    People paste the connection string DigitalOcean shows them, which uses the
    sync ``postgresql://`` scheme. Rejecting that would be unhelpful.
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("sqlite://") and "+aiosqlite" not in url:
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


def get_engine() -> AsyncEngine:
    """Returns the process-wide engine, creating it on first use."""
    global _engine, _session_factory

    if _engine is None:
        url = _normalise_url(settings.app.database_url)
        is_sqlite = url.startswith("sqlite")

        kwargs = {"echo": False, "future": True}
        if is_sqlite:
            # SQLite has no server-side pool to size, and a short timeout turns
            # concurrent writes into errors instead of brief waits.
            kwargs["connect_args"] = {"timeout": 30}
        else:
            kwargs.update(pool_size=5, max_overflow=10, pool_pre_ping=True, pool_recycle=1800)

        _engine = create_async_engine(url, **kwargs)
        _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)

        # Log the backend without the credentials.
        backend = url.split("://", 1)[0]
        logger.info(
            f"Database engine created ({backend}).",
            extra={"event": "db_engine_created", "backend": backend},
        )

    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Returns the session factory, creating the engine if needed."""
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None
    return _session_factory


async def init_database() -> None:
    """Creates any missing tables and enables SQLite foreign keys.

    Schema changes beyond additive table creation should go through Alembic;
    this exists so a fresh install works with no migration step.
    """
    engine = get_engine()

    if engine.url.get_backend_name() == "sqlite":
        from sqlalchemy import event

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_sqlite_pragmas(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # WAL lets the webhook write while the dashboard reads.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    # Importing the models registers them on Base.metadata.
    from app.db import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database schema ready.", extra={"event": "db_schema_ready"})


async def close_database() -> None:
    """Disposes of the engine on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database engine disposed.", extra={"event": "db_engine_closed"})


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a session that commits or rolls back."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def session_scope():
    """Returns a session context manager for use outside a request.

    Background tasks and the webhook handler use this rather than the FastAPI
    dependency.
    """
    return get_session_factory()()
