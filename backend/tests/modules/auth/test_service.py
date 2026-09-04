"""Unit tests for ``AuthService`` (design.md §4-1 / §4-2, tasks.md §2.7)."""

from datetime import UTC, datetime

import pytest
from app.core.exceptions import AuthenticationError
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    hash_password,
    hash_token,
    verify_password,
)
from app.modules.auth import service as service_module
from app.modules.auth.service import SESSION_TTL, AuthService

from tests.modules.auth.fakes import FakeSessionRepository, FakeUserRepository, make_user


def _service(users: FakeUserRepository, sessions: FakeSessionRepository) -> AuthService:
    return AuthService(users, sessions)  # type: ignore[arg-type]


async def test_login_with_wrong_password_is_401() -> None:
    user = make_user(email="a@example.com", password_hash=hash_password("right"))
    svc = _service(FakeUserRepository([user]), FakeSessionRepository())

    with pytest.raises(AuthenticationError):
        await svc.login("a@example.com", "wrong")


async def test_login_with_unknown_email_still_verifies_a_dummy_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Enumeration guard (design.md §4-2): the unknown-email branch must spend the
    # same Argon2 cost as a real check.
    calls: list[str] = []

    def spy(hashed: str, password: str) -> bool:
        calls.append(hashed)
        return verify_password(hashed, password)

    monkeypatch.setattr(service_module, "verify_password", spy)
    svc = _service(FakeUserRepository([]), FakeSessionRepository())

    with pytest.raises(AuthenticationError):
        await svc.login("nobody@example.com", "whatever")

    assert calls == [DUMMY_PASSWORD_HASH]


async def test_login_success_stores_only_the_token_hash_and_a_14_day_expiry() -> None:
    user = make_user(email="a@example.com", password_hash=hash_password("right"))
    sessions = FakeSessionRepository()
    svc = _service(FakeUserRepository([user]), sessions)

    before = datetime.now(UTC)
    result = await svc.login("a@example.com", "right")

    assert result.user is user
    assert len(sessions.created) == 1
    stored = sessions.created[0]
    assert stored.user_id == user.id
    assert stored.token_hash == hash_token(result.token)
    assert stored.token_hash != result.token  # raw token is never persisted
    assert result.expires_at == stored.expires_at
    assert abs((result.expires_at - (before + SESSION_TTL)).total_seconds()) < 5


async def test_logout_revokes_the_hashed_token() -> None:
    sessions = FakeSessionRepository()
    svc = _service(FakeUserRepository([]), sessions)

    await svc.logout("some-raw-token")

    assert sessions.revoked == [hash_token("some-raw-token")]


async def test_get_user_treats_a_vanished_user_as_an_invalid_session() -> None:
    svc = _service(FakeUserRepository([]), FakeSessionRepository())

    with pytest.raises(AuthenticationError):
        await svc.get_user(999)
