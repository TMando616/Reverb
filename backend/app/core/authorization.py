"""Actor / Permission / Role と企画の認可器（design.md §5）。

認可の判断はここ、つまり Service 層の届く範囲で行う。HTTP 層では行わない
（design.md §2-2）。``core`` は ``app.modules`` を import してはいけない
（.importlinter で強制）ため、メンバーシップのデータは構造的プロトコルである
``MemberRoleReader`` を経由して届く（design.md §5-2）。
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.core.exceptions import ForbiddenError, NotFoundError


@dataclass(frozen=True, slots=True)
class Actor:
    """認証済みの呼び出し元。Service が受け取る唯一の identity オブジェクト。"""

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
    CONTENT_WRITE = "content:write"  # 作成・更新・削除
    CONTENT_TRANSITION = "content:transition"  # 状態遷移


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

# demo アカウントは role に関わらずこの集合に固定される（design.md §5-2）。
VIEW_ONLY: frozenset[Permission] = frozenset({Permission.PROJECT_VIEW, Permission.CONTENT_VIEW})


class MemberRoleReader(Protocol):
    """メンバーシップ照会のための構造的型。``core`` を module 非依存に保つ。"""

    async def role_of(self, user_id: int, project_id: int) -> Role | None: ...


class ProjectAuthorizer:
    def __init__(self, members: MemberRoleReader) -> None:
        self._members = members

    async def require(self, actor: Actor, project_id: int, perm: Permission) -> Role:
        """``perm`` が許可されていれば actor の role を返す。許可されていなければ例外。

        非メンバー -> 404（企画の存在自体を隠す）。権限を持たないメンバー -> 403。
        demo -> 権限を VIEW_ONLY との積集合に絞る。
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
    """``project_id`` がまだ存在しない操作を守るガード（design.md §5-3）。

    ``POST /projects`` と招待受諾が対象。demo アカウントはここで弾く必要があるが、
    ``ProjectAuthorizer.require`` はまだ走らせられない（project がまだ無いため）。
    """
    if actor.is_demo:
        raise ForbiddenError("demo account is read-only")
