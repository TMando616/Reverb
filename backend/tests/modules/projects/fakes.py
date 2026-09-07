"""In-memory doubles for the projects repositories (design.md §13).

Service unit tests inject these so the project / member / invitation rules run
without a database. SQL-shaped behaviour that these cannot express (the
``FOR UPDATE`` lock, the ``expires_at`` filter under real time) is left to the
API integration tests in tasks.md §7.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from app.core.authorization import Role
from app.modules.auth.models import User
from app.modules.projects.models import Invitation, Project, ProjectMember


def make_user(*, id: int, display_name: str = "Test User", email: str | None = None) -> User:
    user = User(
        email=email or f"user{id}@example.com",
        password_hash="x",
        display_name=display_name,
        is_demo=False,
    )
    user.id = id
    return user


class FakeProjectRepository:
    def __init__(self) -> None:
        self._by_id: dict[int, Project] = {}
        self._membership: dict[int, list[tuple[Project, Role]]] = {}
        self._seq = 0

    async def create(self, *, name: str, created_by: int) -> Project:
        self._seq += 1
        project = Project(name=name, created_by=created_by)
        project.id = self._seq
        project.created_at = datetime.now(UTC)
        self._by_id[project.id] = project
        return project

    async def get(self, project_id: int) -> Project | None:
        return self._by_id.get(project_id)

    async def list_for_user(self, user_id: int) -> Sequence[tuple[Project, Role]]:
        return list(self._membership.get(user_id, []))

    def seed_membership(self, user_id: int, project: Project, role: Role) -> None:
        """Register a (project, role) pair that ``list_for_user`` should return."""
        self._by_id[project.id] = project
        self._seq = max(self._seq, project.id)
        self._membership.setdefault(user_id, []).append((project, role))


class FakeProjectMemberRepository:
    """Also serves as the ``MemberRoleReader`` for a real ``ProjectAuthorizer``."""

    def __init__(self, members: Sequence[tuple[int, int, Role]] = (), users: Sequence[User] = ()):
        self._rows: dict[tuple[int, int], ProjectMember] = {}
        self._users = {u.id: u for u in users}
        self._seq = 0
        for project_id, user_id, role in members:
            self._insert(project_id, user_id, role)

    def _insert(self, project_id: int, user_id: int, role: Role) -> ProjectMember:
        self._seq += 1
        row = ProjectMember(project_id=project_id, user_id=user_id, role=role.value)
        row.id = self._seq
        row.created_at = datetime.now(UTC)
        self._rows[(project_id, user_id)] = row
        return row

    async def role_of(self, user_id: int, project_id: int) -> Role | None:
        row = self._rows.get((project_id, user_id))
        return Role(row.role) if row is not None else None

    async def get(self, project_id: int, user_id: int) -> ProjectMember | None:
        return self._rows.get((project_id, user_id))

    async def list_members(self, project_id: int) -> Sequence[tuple[ProjectMember, User]]:
        return [
            (row, self._users[uid])
            for (pid, uid), row in self._rows.items()
            if pid == project_id and uid in self._users
        ]

    async def lock_and_count_owners(self, project_id: int) -> int:
        return sum(
            1
            for (pid, _), row in self._rows.items()
            if pid == project_id and row.role == Role.OWNER.value
        )

    async def add(self, *, project_id: int, user_id: int, role: Role) -> None:
        # ON CONFLICT DO NOTHING: an existing membership is never overwritten.
        if (project_id, user_id) not in self._rows:
            self._insert(project_id, user_id, role)

    async def update_role(self, project_id: int, user_id: int, role: Role) -> None:
        self._rows[(project_id, user_id)].role = role.value

    async def remove(self, project_id: int, user_id: int) -> None:
        self._rows.pop((project_id, user_id), None)


class FakeInvitationRepository:
    def __init__(self) -> None:
        self._by_id: dict[int, Invitation] = {}
        self._seq = 0

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
        self._seq += 1
        invitation = Invitation(
            project_id=project_id,
            email=email,
            role=role.value,
            token_hash=token_hash,
            expires_at=expires_at,
            created_by=created_by,
        )
        invitation.id = self._seq
        invitation.accepted_at = None
        invitation.accepted_user_id = None
        self._by_id[invitation.id] = invitation
        return invitation

    async def find_valid_by_token_hash(self, token_hash: str) -> Invitation | None:
        now = datetime.now(UTC)
        for invitation in self._by_id.values():
            if (
                invitation.token_hash == token_hash
                and invitation.accepted_at is None
                and invitation.expires_at > now
            ):
                return invitation
        return None

    async def mark_accepted(self, invitation_id: int, *, accepted_user_id: int) -> None:
        invitation = self._by_id[invitation_id]
        invitation.accepted_at = datetime.now(UTC)
        invitation.accepted_user_id = accepted_user_id

    def seed(self, invitation: Invitation) -> None:
        self._seq = max(self._seq, invitation.id)
        self._by_id[invitation.id] = invitation
