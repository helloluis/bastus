"""Async engine/session management.

DATABASE_URL selects the backend: Postgres on the VPS
(`postgresql+asyncpg://...`) and SQLite for local dev/tests (the default). The ORM
is written to work on both.
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from bastus.db.models import Base

DEFAULT_URL = "sqlite+aiosqlite:///./data/bastus.db"


def _normalize(url: str) -> str:
    # Accept plain postgres URLs and route them to the async driver.
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


class Database:
    def __init__(self, url: str | None = None) -> None:
        self.url = _normalize(url or os.getenv("DATABASE_URL", DEFAULT_URL))
        if self.url.startswith("sqlite"):
            os.makedirs("data", exist_ok=True)
        self.engine: AsyncEngine = create_async_engine(self.url, future=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    def session(self) -> AsyncSession:
        return self.session_factory()

    async def dispose(self) -> None:
        await self.engine.dispose()


_db: Database | None = None


def get_database() -> Database:
    global _db
    if _db is None:
        _db = Database()
    return _db
