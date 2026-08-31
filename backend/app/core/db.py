"""Async engine and session factory.

Only ``repository.py`` / ``models.py`` / ``deps.py`` / ``cli.py`` / ``migrations/``
are allowed to import from here (see design.md §2-2, enforced by .importlinter).
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

engine = create_async_engine(get_settings().database_url, future=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one request-scoped session.

    Commit/flush boundaries are the Service layer's responsibility
    (design.md §4-4). This dependency only owns lifecycle + rollback.
    """
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
