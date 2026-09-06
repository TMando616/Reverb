"""Business rules and authorization for the projects module (企画・メンバー・招待).

Knows nothing about HTTP (no ``fastapi`` / ``Request``) and never holds an
``AsyncSession`` directly — repositories are injected in (design.md §2-2).
Authorization is an explicit first line in each method, not a ``Depends`` guard,
so an MCP / job caller runs the same checks (design.md §5-2, F5).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.authorization import (
    Actor,
    Permission,
    ProjectAuthorizer,
    Role,
    require_not_demo,
)
from app.core.exceptions import NotFoundError
from app.modules.projects.models import Project
from app.modules.projects.repository import ProjectMemberRepository, ProjectRepository


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
