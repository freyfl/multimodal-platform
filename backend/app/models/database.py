"""Lazy server-local MySQL engine and sessions; importing performs no I/O."""

import ssl
from collections.abc import AsyncIterator

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings
from app.errors import ServiceError


class Base(DeclarativeBase):
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_engine": "InnoDB"}


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None


def get_engine() -> AsyncEngine:
    """Create a pool on first use, without opening a database connection."""
    global _engine, _session_factory
    if _engine is None:
        settings.require_config("mysql")
        connect_args = {"connect_timeout": settings.MYSQL_CONNECT_TIMEOUT}
        if settings.MYSQL_SSL_ENABLED:
            try:
                connect_args["ssl"] = ssl.create_default_context(
                    cafile=settings.MYSQL_SSL_CA or None
                )
            except (OSError, ssl.SSLError):
                raise ServiceError("mysql", "invalid_request") from None
        _engine = create_async_engine(
            settings.mysql_url,
            # SQL echo can expose password hashes, tokens and user credentials.
            echo=False,
            hide_parameters=True,
            pool_size=5,
            max_overflow=10,
            pool_recycle=300,
            pool_timeout=30,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def async_session_maker(**kwargs) -> AsyncSession:
    """Use ``async with async_session_maker() as session``; commit explicitly."""
    get_engine()
    return _session_factory(**kwargs)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency; never auto-commit a partially completed request."""
    async with async_session_maker() as session:
        try:
            yield session
        except SQLAlchemyError:
            await session.rollback()
            raise ServiceError("mysql", "unavailable") from None
        except BaseException:
            await session.rollback()
            raise


async def init_db() -> None:
    """Apply versioned schema migrations in an already provisioned database."""
    from app.models.migrations import migrate

    try:
        await migrate(get_engine())
    except SQLAlchemyError:
        raise ServiceError("mysql", "unavailable") from None


async def close_db() -> None:
    """Dispose the pool on shutdown; repeated calls and unused engines are safe."""
    global _engine, _session_factory
    engine = _engine
    _engine = None
    _session_factory = None
    if engine is not None:
        await engine.dispose()
