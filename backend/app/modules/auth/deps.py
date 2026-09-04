"""Dependency wiring for the auth module.

The assembly role: allowed to import both router-facing and repository-facing
code, so it is intentionally excluded from the layers contract (design.md §11).
"""

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import Actor
from app.core.db import get_session
from app.core.exceptions import AuthenticationError
from app.core.security import hash_token
from app.modules.auth.repository import SessionRepository, UserRepository
from app.modules.auth.service import AuthService


def _parse_bearer(authorization: str) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("malformed Authorization header")
    return token.strip()


def get_current_token(authorization: str | None = Header(default=None)) -> str:
    """The raw bearer token, or 401. ``Header(default=None)`` keeps a missing
    header a 401 rather than FastAPI's 422 (design.md §4-3).
    """
    if authorization is None:
        raise AuthenticationError()
    return _parse_bearer(authorization)


async def get_current_actor(
    token: Annotated[str, Depends(get_current_token)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Actor:
    """Resolve the caller from the bearer token (design.md §4-3).

    One query joins ``sessions`` to ``users`` so ``is_demo`` is always present.
    Missing / malformed / revoked / expired token -> 401.
    """
    row = await SessionRepository(session).find_valid_with_user(hash_token(token))
    if row is None:
        raise AuthenticationError()
    return Actor(user_id=row.user.id, is_demo=row.user.is_demo)


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthService:
    return AuthService(UserRepository(session), SessionRepository(session))


CurrentActor = Annotated[Actor, Depends(get_current_actor)]
