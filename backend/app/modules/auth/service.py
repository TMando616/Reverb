"""auth モジュールの業務ルールと認可（認証・現在のユーザー解決）。

HTTP のことは知らない（``fastapi`` / ``Request`` は import しない）し、
``AsyncSession`` を直接持つこともない ── repository は注入される（design.md §2-2）。
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.exceptions import AuthenticationError
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    generate_token,
    hash_token,
    verify_password,
)
from app.modules.auth.models import User
from app.modules.auth.repository import SessionRepository, UserRepository

# セッションの有効期間（design.md §4-1）。信頼できる唯一の値：BFF はここが
# 生成する ``expires_at`` から Cookie の ``maxAge`` を導出する（design.md §12-1）。
SESSION_TTL = timedelta(days=14)


@dataclass(frozen=True, slots=True)
class LoginResult:
    """``login`` が返すもの：生のトークン（この1回だけ表示される）とユーザー。"""

    token: str
    expires_at: datetime
    user: User


class AuthService:
    def __init__(self, users: UserRepository, sessions: SessionRepository) -> None:
        self._users = users
        self._sessions = sessions

    async def login(self, email: str, password: str) -> LoginResult:
        """資格情報を検証してセッションを開く。失敗時は ``AuthenticationError``。

        email が未登録でも、固定のダミーハッシュに対して ``verify_password`` を
        1回走らせる。これによりレスポンス時間からアドレスの登録有無が漏れない
        （design.md §4-2）。
        """
        user = await self._users.get_by_email(email)
        if user is None:
            verify_password(DUMMY_PASSWORD_HASH, password)
            raise AuthenticationError("invalid email or password")
        if not verify_password(user.password_hash, password):
            raise AuthenticationError("invalid email or password")

        token = generate_token()
        expires_at = datetime.now(UTC) + SESSION_TTL
        await self._sessions.create(
            user_id=user.id, token_hash=hash_token(token), expires_at=expires_at
        )
        return LoginResult(token=token, expires_at=expires_at, user=user)

    async def logout(self, token: str) -> None:
        """``token`` の背後にあるセッションを失効させる。冪等。"""
        await self._sessions.revoke(hash_token(token))

    async def get_user(self, user_id: int) -> User:
        """``GET /auth/me`` のために、呼び出し元自身のレコードを読み込む。

        解決済みの ``Actor`` が指すユーザーが既に消えていた場合は、404 ではなく
        無効なセッション（401）として扱う。
        """
        user = await self._users.get(user_id)
        if user is None:
            raise AuthenticationError()
        return user
