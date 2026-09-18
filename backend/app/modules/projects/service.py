"""projects モジュールの業務ルールと認可（企画・メンバー・招待）。

HTTP のことは知らない（``fastapi`` / ``Request`` は import しない）し、
``AsyncSession`` を直接持つこともない ── repository は注入される（design.md §2-2）。
認可は ``Depends`` によるガードではなく、各メソッドの明示的な最初の一文なので、
MCP やジョブからの呼び出しも同じチェックを通る（design.md §5-2、F5）。
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
from app.core.exceptions import AuthenticationError, ForbiddenError, NotFoundError
from app.core.security import generate_token, hash_password, hash_token
from app.modules.auth.repository import UserRepository
from app.modules.projects.models import Invitation, Project, ProjectMember
from app.modules.projects.repository import (
    InvitationRepository,
    ProjectMemberRepository,
    ProjectRepository,
)

# リンク方式の招待は発行から7日で期限切れ（design.md §9-1）。
INVITATION_TTL = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class ProjectWithRole:
    """企画と、その中での呼び出し元の role の組 ── 企画を返すすべての
    エンドポイントが必要とする形（design.md §6-1）。
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
        """企画を作成し、作成者を ``owner`` として登録する。

        両方の行が1つのリクエストトランザクションに収まる（design.md §4-4）。
        demo アカウントは作成できない ── まだ ``project_id`` が存在せず
        project の認可器が判断できないので、単独のガードを使う（design.md §5-3）。
        """
        require_not_demo(actor)
        project = await self._projects.create(name=name, created_by=actor.user_id)
        await self._members.add(project_id=project.id, user_id=actor.user_id, role=Role.OWNER)
        return ProjectWithRole(project=project, role=Role.OWNER)

    async def list_mine(self, actor: Actor) -> Sequence[ProjectWithRole]:
        """呼び出し元が所属する企画。非所属はここでは単に空リストになる ──
        隠すべき企画は無い（design.md §6-1）。
        """
        rows = await self._projects.list_for_user(actor.user_id)
        return [ProjectWithRole(project=project, role=role) for project, role in rows]

    async def get(self, actor: Actor, project_id: int) -> ProjectWithRole:
        """企画1件。非メンバーには 403 ではなく 404 を返す ── 企画の存在自体を
        隠す（design.md §5-2）。
        """
        role = await self._authz.require(actor, project_id, Permission.PROJECT_VIEW)
        project = await self._projects.get(project_id)
        if project is None:
            raise NotFoundError("project")
        return ProjectWithRole(project=project, role=role)


@dataclass(frozen=True, slots=True)
class InvitationCreated:
    """発行した招待と、owner が受諾者に手渡す相対パス（M0 にメール送信は無い、
    design.md §9-1）。
    """

    invitation: Invitation
    accept_path: str


@dataclass(frozen=True, slots=True)
class MemberView:
    """メンバーの行と user を結合したもの。メンバー一覧のための形（design.md §6-1）。"""

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
        """リンク方式の招待を発行する。保存するのは ``sha256(token)`` だけで、
        生のトークンは戻り値のパスにだけ存在する（design.md §9-1）。
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
        """メンバーの role を変更する。最後に残った owner の降格は拒否する
        （design.md §9-3）。role の変更は招待受諾からは決して発生しない（§9-2）
        ので、このガードが要るのはこの経路だけ。
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
        """メンバーを除名する。最後に残った owner の除名は拒否する（§9-3）。"""
        await self._authz.require(actor, project_id, Permission.PROJECT_MANAGE_MEMBERS)
        member = await self._members.get(project_id, user_id)
        if member is None:
            raise NotFoundError("member")
        if member.role == Role.OWNER.value:
            await self._guard_not_last_owner(project_id)
        await self._members.remove(project_id, user_id)

    async def _guard_not_last_owner(self, project_id: int) -> None:
        # owner 行を数える前に FOR UPDATE でロックすることで、同時に走った
        # 降格・除名がカウントを1未満にすり抜けさせない（design.md §9-3）。
        if await self._members.lock_and_count_owners(project_id) <= 1:
            raise ForbiddenError("cannot demote or remove the last owner")


@dataclass(frozen=True, slots=True)
class AcceptResult:
    """受諾の結果：どの企画か、そして呼び出し元の*実効*role ── すでに
    メンバーだった場合はその既存の role（§9-2）。
    """

    project_id: int
    role: Role


class InvitationService:
    def __init__(
        self,
        invitations: InvitationRepository,
        members: ProjectMemberRepository,
        users: UserRepository,
    ) -> None:
        self._invitations = invitations
        self._members = members
        self._users = users

    async def accept(
        self,
        actor: Actor | None,
        token: str,
        *,
        display_name: str | None,
        password: str | None,
    ) -> AcceptResult:
        """招待を受諾する（design.md §9-1）。

        トークン自体が認可。無効・期限切れ・受諾済みはすべて同じ404に収束させ、
        探りを入れても区別できないようにする（§6-3）。既にログイン済みの demo
        アカウントは拒否する（§5-3）。未ログインの呼び出し元は招待先の email で
        登録する。既存の role は決して上書きしない（§9-2）ので、レスポンスには
        メンバーが実際に保持している role が乗る。
        """
        invitation = await self._invitations.find_valid_by_token_hash(hash_token(token))
        if invitation is None:
            raise NotFoundError("invitation")

        if actor is not None:
            if actor.is_demo:
                raise ForbiddenError("demo account is read-only")
            user_id = actor.user_id
        else:
            user_id = await self._register_acceptor(invitation, display_name, password)

        await self._members.add(
            project_id=invitation.project_id,
            user_id=user_id,
            role=Role(invitation.role),
        )
        await self._invitations.mark_accepted(invitation.id, accepted_user_id=user_id)

        effective_role = await self._members.role_of(user_id, invitation.project_id)
        assert effective_role is not None  # 直前でメンバーシップを保証済み
        return AcceptResult(project_id=invitation.project_id, role=effective_role)

    async def _register_acceptor(
        self, invitation: Invitation, display_name: str | None, password: str | None
    ) -> int:
        # 送信先メールの無いリンク招待は、既にログイン済みのユーザーしか
        # 受諾できない ── 登録先のアドレスが無いため。
        if invitation.email is None:
            raise AuthenticationError("sign in to accept this invitation")
        if not display_name or not password:
            raise AuthenticationError("display_name and password are required to register")
        if await self._users.get_by_email(invitation.email) is not None:
            raise AuthenticationError("an account already exists for this email; sign in first")
        user = await self._users.create(
            email=invitation.email,
            password_hash=hash_password(password),
            display_name=display_name,
        )
        return user.id
