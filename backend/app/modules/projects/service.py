"""Business rules and authorization for the projects module (企画・メンバー・招待).

Knows nothing about HTTP (no ``fastapi`` / ``Request``) and never holds an
``AsyncSession`` directly — repositories are injected in (design.md §2-2).
Authorization is an explicit first line in each method, not a ``Depends`` guard,
so an MCP / job caller runs the same checks (design.md §5-2, F5).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.authorization import (
    Actor,
    Permission,
    ProjectAuthorizer,
    Role,
    require_not_demo,
)
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import generate_token, hash_token
from app.modules.projects.models import Invitation, Project, ProjectMember
from app.modules.projects.repository import (
    InvitationRepository,
    ProjectMemberRepository,
    ProjectRepository,
)

# Link-only invitations expire 7 days after issue (design.md §9-1).
INVITATION_TTL = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class ProjectWithRole:
    """A project paired with the caller's role in it — the shape every
    project-returning endpoint needs (design.md §6-1).
    """

    project: Project
    role: Role


class ProjectService:
    def __init__(
        self,
        projects: ProjectRepository,
        members: ProjectMemberRepository,
        authz: ProjectAuthorizer,
    ) -> None:
        self._projects = projects
        self._members = members
        self._authz = authz

    async def create(self, actor: Actor, *, name: str) -> ProjectWithRole:
        """Create a project and enrol the creator as its ``owner``.

        Both rows land in the one request transaction (design.md §4-4). Demo
        accounts cannot create — there is no ``project_id`` yet for the project
        authorizer to judge, so the standalone guard applies (design.md §5-3).
        """
        require_not_demo(actor)
        project = await self._projects.create(name=name, created_by=actor.user_id)
        await self._members.add(project_id=project.id, user_id=actor.user_id, role=Role.OWNER)
        return ProjectWithRole(project=project, role=Role.OWNER)

    async def list_mine(self, actor: Actor) -> Sequence[ProjectWithRole]:
        """Projects the caller belongs to. Non-membership just means an empty
        list here — there is no project to hide (design.md §6-1).
        """
        rows = await self._projects.list_for_user(actor.user_id)
        return [ProjectWithRole(project=project, role=role) for project, role in rows]

    async def get(self, actor: Actor, project_id: int) -> ProjectWithRole:
        """One project. A non-member gets 404, not 403 — the project's
        existence is hidden (design.md §5-2).
        """
        role = await self._authz.require(actor, project_id, Permission.PROJECT_VIEW)
        project = await self._projects.get(project_id)
        if project is None:
            raise NotFoundError("project")
        return ProjectWithRole(project=project, role=role)


@dataclass(frozen=True, slots=True)
class InvitationCreated:
    """The issued invitation plus the relative accept path the owner hands over
    (M0 has no mail delivery, design.md §9-1).
    """

    invitation: Invitation
    accept_path: str


@dataclass(frozen=True, slots=True)
class MemberView:
    """A member row joined with its user, for the members list (design.md §6-1)."""

    user_id: int
    display_name: str
    email: str
    role: Role
    joined_at: datetime


class MemberService:
    def __init__(
        self,
        members: ProjectMemberRepository,
        invitations: InvitationRepository,
        authz: ProjectAuthorizer,
    ) -> None:
        self._members = members
        self._invitations = invitations
        self._authz = authz

    async def invite(
        self, actor: Actor, project_id: int, *, role: Role, email: str | None
    ) -> InvitationCreated:
        """Issue a link invitation. Only ``sha256(token)`` is stored; the raw
        token lives only in the returned path (design.md §9-1).
        """
        await self._authz.require(actor, project_id, Permission.PROJECT_MANAGE_MEMBERS)
        token = generate_token()
        invitation = await self._invitations.create(
            project_id=project_id,
            email=email,
            role=role,
            token_hash=hash_token(token),
            expires_at=datetime.now(UTC) + INVITATION_TTL,
            created_by=actor.user_id,
        )
        return InvitationCreated(invitation=invitation, accept_path=f"/invite/{token}")

    async def list_members(self, actor: Actor, project_id: int) -> Sequence[MemberView]:
        await self._authz.require(actor, project_id, Permission.PROJECT_VIEW)
        rows = await self._members.list_members(project_id)
        return [
            MemberView(
                user_id=member.user_id,
                display_name=user.display_name,
                email=user.email,
                role=Role(member.role),
                joined_at=member.created_at,
            )
            for member, user in rows
        ]

    async def change_role(
        self, actor: Actor, project_id: int, user_id: int, *, role: Role
    ) -> ProjectMember:
        """Change a member's role. Demoting the sole remaining owner is refused
        (design.md §9-3); role changes never flow through invitation acceptance
        (§9-2), so this is the only path that needs the guard.
        """
        await self._authz.require(actor, project_id, Permission.PROJECT_MANAGE_MEMBERS)
        member = await self._members.get(project_id, user_id)
        if member is None:
            raise NotFoundError("member")
        if member.role == Role.OWNER.value and role is not Role.OWNER:
            await self._guard_not_last_owner(project_id)
        await self._members.update_role(project_id, user_id, role)
        return member

    async def remove(self, actor: Actor, project_id: int, user_id: int) -> None:
        """Remove a member. Removing the sole remaining owner is refused (§9-3)."""
        await self._authz.require(actor, project_id, Permission.PROJECT_MANAGE_MEMBERS)
        member = await self._members.get(project_id, user_id)
        if member is None:
            raise NotFoundError("member")
        if member.role == Role.OWNER.value:
            await self._guard_not_last_owner(project_id)
        await self._members.remove(project_id, user_id)

    async def _guard_not_last_owner(self, project_id: int) -> None:
        # Owner rows are locked FOR UPDATE before counting so a concurrent
        # demotion / removal cannot slip the count below one (design.md §9-3).
        if await self._members.lock_and_count_owners(project_id) <= 1:
            raise ForbiddenError("cannot demote or remove the last owner")
