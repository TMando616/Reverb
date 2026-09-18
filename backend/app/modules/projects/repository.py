"""projects モジュールの永続化 ── DB を叩く唯一の層。

``AsyncSession`` を受け取り、業務ルールは持たない（ADR-0009）。すべての
getter は ``project_id`` を受け取ってそれで絞り込むので、企画をまたいだ読み取りは
起こり得ない（design.md §5-2）。書き込みは ``flush()`` するので、生成された id と
制約違反がハンドラでまだマッピングできるタイミングで表面化する（design.md §4-4）。
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
        """ユーザーが所属する企画を、新しい順に、それぞれの role とともに返す。"""
        result = await self._session.execute(
            select(Project, ProjectMember.role)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user_id)
            .order_by(Project.created_at.desc())
        )
        return [(project, Role(role)) for project, role in result.all()]


class ProjectMemberRepository:
    """``role_of`` によって ``core.authorization.MemberRoleReader`` を構造的に
    満たす ── Protocol を継承はしないので、``core`` は ``app.modules`` からの
    import を持たずに済む（design.md §5-2）。
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
        """企画のメンバーを、その user 行とともに join した順で返す。"""
        result = await self._session.execute(
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.created_at)
        )
        return [(member, user) for member, user in result.all()]

    async def lock_and_count_owners(self, project_id: int) -> int:
        """``SELECT ... FOR UPDATE`` で owner 行をロックしてから数える。これにより、
        同時に走った降格・除名が最後の owner ガードのカウントをすり抜けない
        （design.md §9-3）。
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
        """メンバーシップを挿入する。既に存在する場合は何もしない。

        ``UNIQUE (project_id, user_id)`` への ``ON CONFLICT DO NOTHING`` が、
        招待受諾が既存の role を上書き（＝黙って降格させること）しないようにする
        （design.md §9-2）。
        """
        await self._session.execute(
            pg_insert(ProjectMember)
            .values(project_id=project_id, user_id=user_id, role=role.value)
            .on_conflict_do_nothing(constraint="uq_project_members_project_user")
        )
        await self._session.flush()

    async def update_role(self, project_id: int, user_id: int, role: Role) -> None:
        # synchronize_session により、既にロード済みの ProjectMember を
        # identity map 上でも一致させる。呼び出し元はそのまま返せる。
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
        """``token_hash`` の招待を、まだ使える場合に限って返す：未受諾かつ
        ``expires_at`` を過ぎていないこと（design.md §9-1）。それ以外は ``None`` を
        返し、呼び出し元が単一の 404 にマッピングする（§6-3）。
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
        """``accepted_at``（サーバークロック）を打ち、誰が受諾したかを記録する。"""
        await self._session.execute(
            update(Invitation)
            .where(Invitation.id == invitation_id)
            .values(accepted_at=func.now(), accepted_user_id=accepted_user_id)
        )
        await self._session.flush()
