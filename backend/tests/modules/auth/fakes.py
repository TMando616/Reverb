"""In-memory doubles for the auth repositories (design.md §13).

Service / deps unit tests inject these so the auth logic can be exercised
without a database. The real ``find_valid_with_user`` SQL filter (revoked /
expired) is covered by the API integration tests in tasks.md §7.
"""

from datetime import datetime
from types import SimpleNamespace

from app.modules.auth.models import User


class FakeUserRepository:
    def __init__(self, users: list[User] | None = None) -> None:
        users = users or []
        self._by_email = {u.email: u for u in users}
        self._by_id = {u.id: u for u in users}
        self.created: list[User] = []

    async def get(self, user_id: int) -> User | None:
        return self._by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return self._by_email.get(email)

    async def create(
        self, *, email: str, password_hash: str, display_name: str, is_demo: bool = False
    ) -> User:
        user = User(
            email=email,
            password_hash=password_hash,
            display_name=display_name,
            is_demo=is_demo,
        )
        user.id = max(self._by_id, default=0) + 1
        self._by_email[email] = user
        self._by_id[user.id] = user
        self.created.append(user)
        return user


class FakeSessionRepository:
    def __init__(self, valid: dict[str, SimpleNamespace] | None = None) -> None:
        self.valid = valid or {}  # token_hash -> row (with a ``user`` attribute)
        self.created: list[SimpleNamespace] = []
        self.revoked: list[str] = []

    async def create(
        self, *, user_id: int, token_hash: str, expires_at: datetime
    ) -> SimpleNamespace:
        row = SimpleNamespace(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
        self.created.append(row)
        return row

    async def find_valid_with_user(self, token_hash: str) -> SimpleNamespace | None:
        return self.valid.get(token_hash)

    async def revoke(self, token_hash: str) -> None:
        self.revoked.append(token_hash)


def make_user(
    *, id: int = 1, email: str = "a@example.com", password_hash: str = "x", is_demo: bool = False
) -> User:
    user = User(email=email, password_hash=password_hash, display_name="Test User", is_demo=is_demo)
    user.id = id
    return user
