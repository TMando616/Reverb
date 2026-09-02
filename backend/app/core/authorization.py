"""Actor / Permission / Role and the project authorizer (design.md §5).

Authorization is decided here, in the Service layer's reach, not in HTTP
(design.md §2-2). ``core`` must not import ``app.modules`` (enforced by
.importlinter), so membership data arrives through the ``MemberRoleReader``
structural protocol (design.md §5-2).
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.core.exceptions import ForbiddenError, NotFoundError


@dataclass(frozen=True, slots=True)
class Actor:
    """The authenticated caller. The only identity object Services receive."""

    user_id: int
    is_demo: bool


class Role(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    REVIEWER = "reviewer"


class Permission(StrEnum):
    PROJECT_VIEW = "project:view"
    PROJECT_MANAGE_MEMBERS = "project:manage_members"
    CONTENT_VIEW = "content:view"
    CONTENT_WRITE = "content:write"  # create / update / delete
    CONTENT_TRANSITION = "content:transition"  # status change


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(Permission),
    Role.EDITOR: frozenset(
        {
            Permission.PROJECT_VIEW,
            Permission.CONTENT_VIEW,
            Permission.CONTENT_WRITE,
            Permission.CONTENT_TRANSITION,
        }
    ),
    Role.REVIEWER: frozenset({Permission.PROJECT_VIEW, Permission.CONTENT_VIEW}),
}

# Demo accounts are clamped to this set regardless of role (design.md §5-2).
VIEW_ONLY: frozenset[Permission] = frozenset({Permission.PROJECT_VIEW, Permission.CONTENT_VIEW})


class MemberRoleReader(Protocol):
    """Structural type for the membership lookup. ``core`` stays module-free."""

    async def role_of(self, user_id: int, project_id: int) -> Role | None: ...


class ProjectAuthorizer:
    def __init__(self, members: MemberRoleReader) -> None:
        self._members = members

    async def require(self, actor: Actor, project_id: int, perm: Permission) -> Role:
        """Return the actor's role if ``perm`` is allowed; raise otherwise.

        Non-member -> 404 (the project's existence is hidden). Member without
        the permission -> 403. Demo -> permissions intersected with VIEW_ONLY.
        """
        role = await self._members.role_of(actor.user_id, project_id)
        if role is None:
            raise NotFoundError("project")
        allowed = ROLE_PERMISSIONS[role]
        if actor.is_demo:
            allowed = allowed & VIEW_ONLY
        if perm not in allowed:
            raise ForbiddenError(perm)
        return role


def require_not_demo(actor: Actor) -> None:
    """Guard operations that have no ``project_id`` yet (design.md §5-3).

    Covers ``POST /projects`` and invitation acceptance, where the demo account
    must be blocked but ``ProjectAuthorizer.require`` cannot run.
    """
    if actor.is_demo:
        raise ForbiddenError("demo account is read-only")
