"""Unit tests for the project authorizer (design.md §5-2 / §5-3)."""

import pytest
from app.core.authorization import (
    Actor,
    Permission,
    ProjectAuthorizer,
    Role,
    require_not_demo,
)
from app.core.exceptions import ForbiddenError, NotFoundError


class FakeMembers:
    """In-memory MemberRoleReader: (user_id, project_id) -> Role."""

    def __init__(self, roles: dict[tuple[int, int], Role]) -> None:
        self._roles = roles

    async def role_of(self, user_id: int, project_id: int) -> Role | None:
        return self._roles.get((user_id, project_id))


def _authorizer(roles: dict[tuple[int, int], Role]) -> ProjectAuthorizer:
    return ProjectAuthorizer(FakeMembers(roles))


async def test_non_member_is_hidden_as_not_found() -> None:
    authz = _authorizer({})
    with pytest.raises(NotFoundError):
        await authz.require(Actor(user_id=1, is_demo=False), 99, Permission.PROJECT_VIEW)


async def test_member_without_permission_is_forbidden() -> None:
    authz = _authorizer({(1, 10): Role.REVIEWER})
    with pytest.raises(ForbiddenError):
        await authz.require(Actor(user_id=1, is_demo=False), 10, Permission.CONTENT_WRITE)


async def test_member_with_permission_gets_role_back() -> None:
    authz = _authorizer({(1, 10): Role.EDITOR})
    role = await authz.require(Actor(user_id=1, is_demo=False), 10, Permission.CONTENT_WRITE)
    assert role is Role.EDITOR


async def test_demo_is_clamped_to_view_only_intersection() -> None:
    # Demo owner: reads pass, writes are refused regardless of the owner role.
    authz = _authorizer({(1, 10): Role.OWNER})
    demo = Actor(user_id=1, is_demo=True)

    assert await authz.require(demo, 10, Permission.PROJECT_VIEW) is Role.OWNER
    with pytest.raises(ForbiddenError):
        await authz.require(demo, 10, Permission.CONTENT_WRITE)
    with pytest.raises(ForbiddenError):
        await authz.require(demo, 10, Permission.PROJECT_MANAGE_MEMBERS)


def test_require_not_demo_blocks_demo() -> None:
    with pytest.raises(ForbiddenError):
        require_not_demo(Actor(user_id=1, is_demo=True))


def test_require_not_demo_allows_regular_user() -> None:
    require_not_demo(Actor(user_id=1, is_demo=False))  # does not raise
