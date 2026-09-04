"""Unit tests for ``get_current_actor`` / ``get_current_token`` (design.md §4-3)."""

from types import SimpleNamespace

import pytest
from app.core.authorization import Actor
from app.core.exceptions import AuthenticationError
from app.core.security import hash_token
from app.modules.auth import deps as deps_module
from app.modules.auth.deps import get_current_actor, get_current_token

from tests.modules.auth.fakes import FakeSessionRepository, make_user


def test_missing_header_is_401_not_422() -> None:
    with pytest.raises(AuthenticationError):
        get_current_token(authorization=None)


@pytest.mark.parametrize("header", ["garbage", "Basic abc", "Bearer", "Bearer   "])
def test_malformed_header_is_401(header: str) -> None:
    with pytest.raises(AuthenticationError):
        get_current_token(authorization=header)


def test_bearer_token_is_extracted_case_insensitively() -> None:
    assert get_current_token(authorization="bearer abc.def") == "abc.def"


async def test_valid_token_resolves_to_an_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user(id=7, is_demo=True)
    row = SimpleNamespace(user=user)
    fake = FakeSessionRepository({hash_token("live-token"): row})
    monkeypatch.setattr(deps_module, "SessionRepository", lambda _session: fake)

    actor = await get_current_actor(token="live-token", session=object())  # type: ignore[arg-type]

    assert actor == Actor(user_id=7, is_demo=True)


async def test_unknown_or_revoked_or_expired_token_is_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ``find_valid_with_user`` returning None covers all three cases; the SQL
    # filter itself is exercised by the integration tests (tasks.md §7).
    fake = FakeSessionRepository({})
    monkeypatch.setattr(deps_module, "SessionRepository", lambda _session: fake)

    with pytest.raises(AuthenticationError):
        await get_current_actor(token="whatever", session=object())  # type: ignore[arg-type]
