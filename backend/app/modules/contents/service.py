"""contents モジュールの業務ルールと認可（コンテンツ CRUD・状態遷移）。

HTTP のことは知らない（``fastapi`` / ``Request`` は import しない）し、
``AsyncSession`` を直接持つこともない ── repository は注入される（design.md §2-2）。
認可はすべてのメソッドの最初の一文なので、MCP やジョブからの呼び出しもブラウザと
同じチェックを受ける（design.md §5-2、F5）。
"""

from collections.abc import Sequence

from app.core.authorization import Actor, Permission, ProjectAuthorizer
from app.core.exceptions import NotFoundError, VersionConflictError
from app.modules.contents.models import Content, ContentStatus
from app.modules.contents.repository import ContentRepository, ContentTransitionRepository


class ContentService:
    def __init__(
        self,
        contents: ContentRepository,
        authz: ProjectAuthorizer,
        transitions: ContentTransitionRepository,
    ) -> None:
        self._contents = contents
        self._authz = authz
        self._transitions = transitions

    async def create(self, actor: Actor, project_id: int, *, title: str, body_md: str) -> Content:
        """新しいコンテンツは必ず ``inbox`` から始まる（F6）。"""
        await self._authz.require(actor, project_id, Permission.CONTENT_WRITE)
        return await self._contents.create(
            project_id=project_id,
            title=title,
            body_md=body_md,
            status=ContentStatus.INBOX,
            created_by=actor.user_id,
        )

    async def list(
        self, actor: Actor, project_id: int, *, status: ContentStatus | None = None
    ) -> Sequence[Content]:
        await self._authz.require(actor, project_id, Permission.CONTENT_VIEW)
        return await self._contents.list(project_id, status)

    async def get(self, actor: Actor, project_id: int, content_id: int) -> Content:
        await self._authz.require(actor, project_id, Permission.CONTENT_VIEW)
        return await self._get_or_404(content_id, project_id)

    async def update(
        self,
        actor: Actor,
        project_id: int,
        content_id: int,
        expected_version: int,
        *,
        title: str | None = None,
        body_md: str | None = None,
    ) -> Content:
        """title / body を二段の楽観ロックの下で更新する（design.md §3-3）。

        1段目は、たった今読み込んだ値と ``expected_version`` を比較する。これに
        より、送信前から既に古かったリクエストには何も書き込まず明確な 409 を
        返せる。2段目は flush 時の ``WHERE version = ?``。読み込みと flush の間に
        割り込んだ書き手を捕まえ、repository が同じ 409 にマッピングする。

        変更のない値を送っても UPDATE は発行されず、``version`` はそのまま。
        これは意図した挙動：何も変わっていないなら、他クライアントのコピーが
        古くなったわけでもない。
        """
        await self._authz.require(actor, project_id, Permission.CONTENT_WRITE)
        content = await self._get_or_404(content_id, project_id)
        self._check_version(content, expected_version)
        if title is not None:
            content.title = title
        if body_md is not None:
            content.body_md = body_md
        await self._contents.flush()
        return content

    async def delete(self, actor: Actor, project_id: int, content_id: int) -> None:
        """論理削除（design.md §3-2）。後続スペックがこの行を参照し続けるため。"""
        await self._authz.require(actor, project_id, Permission.CONTENT_WRITE)
        content = await self._get_or_404(content_id, project_id)
        await self._contents.soft_delete(content)

    async def _get_or_404(self, content_id: int, project_id: int) -> Content:
        # project_id で絞り込んでいるので、他企画のコンテンツ id は単に「無い」。
        content = await self._contents.get(content_id, project_id)
        if content is None:
            raise NotFoundError("content")
        return content

    @staticmethod
    def _check_version(content: Content, expected_version: int) -> None:
        if content.version != expected_version:
            raise VersionConflictError()
