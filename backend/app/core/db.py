"""Async engine and session factory.

Only ``repository.py`` / ``models.py`` / ``deps.py`` / ``cli.py`` / ``migrations/``
are allowed to import from here (see design.md §2-2, enforced by .importlinter).
"""

from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings

engine = create_async_engine(get_settings().database_url, future=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class TimestampMixin:
    """``created_at`` / ``updated_at`` filled by the database (design.md §3-1).

    Timestamps are ``timestamptz``; the server clock owns them so rows written
    outside the app (CLI, migrations) stay consistent.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one request == one session == one transaction.

    Services flush but never commit (design.md §4-4). The single ``commit()``
    lives here and runs only if the handler returned without raising. Because
    FastAPI runs post-yield code after the response is sent, write-path Services
    must ``flush()`` before returning so constraint / optimistic-lock errors
    surface while the handler can still turn them into 4xx (design.md §4-4).
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
