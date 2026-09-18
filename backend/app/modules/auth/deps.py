"""auth モジュールの dependency 組み立て。

組み立て役：router 側・repository 側どちらのコードも import してよいので、
層の依存契約からは意図的に除外している（design.md §11）。
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
    """生の bearer トークン、無ければ 401。``Header(default=None)`` にすることで、
    ヘッダー欠落を FastAPI 標準の 422 ではなく 401 にする（design.md §4-3）。
    """
    if authorization is None:
        raise AuthenticationError()
    return _parse_bearer(authorization)


async def get_current_actor(
    token: Annotated[str, Depends(get_current_token)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Actor:
    """bearer トークンから呼び出し元を解決する（design.md §4-3）。

    ``sessions`` と ``users`` を1クエリで join するので ``is_demo`` は常に手に入る。
    トークンが無い・不正・失効・期限切れ -> 401。
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
