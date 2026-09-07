"""Persistence for the projects module — the only layer that talks to the DB.

Receives an ``AsyncSession``; holds no business rules (ADR-0009). Every getter
takes ``project_id`` and filters on it so no cross-project read is possible
(design.md §5-2). Writes ``flush()`` so generated ids and constraint errors
surface while the handler can still map them (design.md §4-4).
"""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import Role
from app.modules.auth.models import User
from app.modules.projects.models import Invitation, Project, ProjectMember


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, name: str, created_by: int) -> Project:
        project = Project(name=name, created_by=created_by)
        self._session.add(project)
        await self._session.flush()
        return project

    async def get(self, project_id: int) -> Project | None:
        return await self._session.get(Project, project_id)

    async def list_for_user(self, user_id: int) -> Sequence[tuple[Project, Role]]:
        """Projects the user belongs to, newest first, each with the user's role."""
        result = await self._session.execute(
            select(Project, ProjectMember.role)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
            .order_by(Project.created_at.desc())
        )
        return [(project, Role(role)) for project, role in result.all()]


class ProjectMemberRepository:
    """Structurally satisfies ``core.authorization.MemberRoleReader`` via
    ``role_of`` — it does not inherit the Protocol, so ``core`` stays free of
    any import from ``app.modules`` (design.md §5-2).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def role_of(self, user_id: int, project_id: int) -> Role | None:
        result = await self._session.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        role = result.scalar_one_or_none()
        return Role(role) if role is not None else None

    async def get(self, project_id: int, user_id: int) -> ProjectMember | None:
        result = await self._session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_members(self, project_id: int) -> Sequence[tuple[ProjectMember, User]]:
        """Members of a project with their user row, in join order."""
        result = await self._session.execute(
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.created_at)
        )
        return [(member, user) for member, user in result.all()]

    async def lock_and_count_owners(self, project_id: int) -> int:
        """Count owner rows under ``SELECT ... FOR UPDATE`` so the last-owner
        guard cannot race a concurrent demotion / removal (design.md §9-3).
        """
        result = await self._session.execute(
            select(ProjectMember.id)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.role == Role.OWNER.value,
            )
            .with_for_update()
        )
        return len(result.all())

    async def add(self, *, project_id: int, user_id: int, role: Role) -> None:
        """Insert a membership, or do nothing if one already exists.

        ``ON CONFLICT DO NOTHING`` on ``UNIQUE (project_id, user_id)`` is what
        keeps invitation acceptance from overwriting (and so silently demoting)
        an existing role (design.md §9-2).
        """
        await self._session.execute(
            pg_insert(ProjectMember)
            .values(project_id=project_id, user_id=user_id, role=role.value)
            .on_conflict_do_nothing(constraint="uq_project_members_project_user")
        )
        await self._session.flush()

    async def update_role(self, project_id: int, user_id: int, role: Role) -> None:
        # synchronize_session keeps an already-loaded ProjectMember in the
        # identity map consistent, so the caller can return it as-is.
        await self._session.execute(
            update(ProjectMember)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
            .values(role=role.value)
            .execution_options(synchronize_session="evaluate")
        )
        await self._session.flush()

    async def remove(self, project_id: int, user_id: int) -> None:
        await self._session.execute(
            delete(ProjectMember)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
            .execution_options(synchronize_session="evaluate")
        )
        await self._session.flush()


class InvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: int,
        email: str | None,
        role: Role,
        token_hash: str,
        expires_at: datetime,
        created_by: int,
    ) -> Invitation:
        invitation = Invitation(
            project_id=project_id,
            email=email,
            role=role.value,
            token_hash=token_hash,
            expires_at=expires_at,
            created_by=created_by,
        )
        self._session.add(invitation)
        await self._session.flush()
        return invitation

    async def find_valid_by_token_hash(self, token_hash: str) -> Invitation | None:
        """The invitation for ``token_hash`` only if it is still usable: not yet
        accepted and not past ``expires_at`` (design.md §9-1). Anything else
        returns ``None`` and the caller maps it to a single 404 (§6-3).
        """
        result = await self._session.execute(
            select(Invitation).where(
                Invitation.token_hash == token_hash,
                Invitation.accepted_at.is_(None),
                Invitation.expires_at > func.now(),
            )
        )
        return result.scalar_one_or_none()

    async def mark_accepted(self, invitation_id: int, *, accepted_user_id: int) -> None:
        """Stamp ``accepted_at`` (server clock) and record who accepted."""
        await self._session.execute(
            update(Invitation)
            .where(Invitation.id == invitation_id)
            .values(accepted_at=func.now(), accepted_user_id=accepted_user_id)
        )
        await self._session.flush()
