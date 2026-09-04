"""Persistence for the auth module — the only layer that talks to the DB.

Receives an ``AsyncSession``; holds no business rules (ADR-0009). Writes
``flush()`` so the caller sees generated ids and constraint errors surface
while the handler can still map them (design.md §4-4).
"""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auth.models import Session, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(
        self, *, email: str, password_hash: str, display_name: str, is_demo: bool = False
    ) -> User:
        user = User(
            email=email,
            password_hash=password_hash,
            display_name=display_name,
            is_demo=is_demo,
        )
        self._session.add(user)
        await self._session.flush()
        return user


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, user_id: int, token_hash: str, expires_at: datetime) -> Session:
        row = Session(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self._session.add(row)
        await self._session.flush()
        return row

    async def find_valid_with_user(self, token_hash: str) -> Session | None:
        """Return the live session for ``token_hash`` with its ``user`` loaded.

        Live == not revoked and not past ``expires_at`` (design.md §4-1). The
        user is eager-loaded in one round trip because ``is_demo`` is needed on
        every request (design.md §4-3).
        """
        result = await self._session.execute(
            select(Session)
            .where(
                Session.token_hash == token_hash,
                Session.revoked_at.is_(None),
                Session.expires_at > func.now(),
            )
            .options(selectinload(Session.user))
        )
        return result.scalar_one_or_none()

    async def revoke(self, token_hash: str) -> None:
        """Stamp ``revoked_at`` on a live session. A no-op if already gone."""
        await self._session.execute(
            update(Session)
            .where(Session.token_hash == token_hash, Session.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )
        await self._session.flush()
