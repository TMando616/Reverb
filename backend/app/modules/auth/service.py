"""Business rules and authorization for the auth module (認証・現在のユーザー解決).

Knows nothing about HTTP (no ``fastapi`` / ``Request``) and never holds an
``AsyncSession`` directly — repositories are injected in (design.md §2-2).
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

# Session lifetime (design.md §4-1). The single source of truth: the BFF derives
# the cookie ``maxAge`` from the ``expires_at`` this produces (design.md §12-1).
SESSION_TTL = timedelta(days=14)


@dataclass(frozen=True, slots=True)
class LoginResult:
    """What ``login`` hands back: the raw token (shown once) plus the user."""

    token: str
    expires_at: datetime
    user: User


class AuthService:
    def __init__(self, users: UserRepository, sessions: SessionRepository) -> None:
        self._users = users
        self._sessions = sessions

    async def login(self, email: str, password: str) -> LoginResult:
        """Verify credentials and open a session, or raise ``AuthenticationError``.

        When the email is unknown we still run one ``verify_password`` against a
        fixed dummy hash so the response time does not reveal whether the address
        is registered (design.md §4-2).
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
        """Revoke the session behind ``token``. Idempotent."""
        await self._sessions.revoke(hash_token(token))

    async def get_user(self, user_id: int) -> User:
        """Load the caller's own record for ``GET /auth/me``.

        A resolved ``Actor`` whose user has since vanished is treated as an
        invalid session (401), not a 404.
        """
        user = await self._users.get(user_id)
        if user is None:
            raise AuthenticationError()
        return user
