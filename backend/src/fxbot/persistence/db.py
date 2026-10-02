"""Async database engine and sessions (SQLite by default, Postgres-ready)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from fxbot.persistence.models import Base

_SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",  # readers never block the writer
    "PRAGMA busy_timeout=5000",
    "PRAGMA foreign_keys=ON",
    "PRAGMA synchronous=NORMAL",
)


def _set_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        for pragma in _SQLITE_PRAGMAS:
            cursor.execute(pragma)
    finally:
        cursor.close()


def _prepare_sqlite_file(url: URL) -> None:
    database = url.database
    if database and database != ":memory:" and not database.startswith("file:"):
        Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True, mode=0o700)


class Database:
    """Owns the engine and session factory. Call ``dispose()`` on shutdown."""

    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        url = make_url(database_url)
        self.dialect = url.get_backend_name()
        if self.dialect == "sqlite":
            _prepare_sqlite_file(url)
            self.engine: AsyncEngine = create_async_engine(url, echo=echo)
            event.listen(self.engine.sync_engine, "connect", _set_sqlite_pragmas)
        else:
            self.engine = create_async_engine(url, echo=echo, pool_pre_ping=True)
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    def __repr__(self) -> str:
        return f"Database(dialect={self.dialect!r})"

    async def create_all(self) -> None:
        """Create missing tables. Alembic migrations take over in stage 5."""
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """A session in a transaction: committed on success, rolled back on error."""
        async with self._sessions() as session, session.begin():
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()
