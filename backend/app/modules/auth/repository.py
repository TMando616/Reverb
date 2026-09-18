"""auth モジュールの永続化 ── DB を叩く唯一の層。

``AsyncSession`` を受け取り、業務ルールは持たない（ADR-0009）。書き込みは
``flush()`` するので、呼び出し元は生成された id を見られ、制約違反もハンドラが
まだマッピングできるタイミングで表面化する（design.md §4-4）。
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
        """``token_hash`` の有効なセッションを、``user`` をロードした状態で返す。

        「有効」とは失効しておらず ``expires_at`` も過ぎていないこと
        （design.md §4-1）。``is_demo`` は毎リクエスト必要なので、user は
        1往復で eager load する（design.md §4-3）。
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
        """有効なセッションに ``revoked_at`` を打つ。既に無ければ何もしない。"""
        await self._session.execute(
            update(Session)
            .where(Session.token_hash == token_hash, Session.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )
        await self._session.flush()
