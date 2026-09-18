"""contents モジュールの永続化 ── DB を叩く唯一の層。

``AsyncSession`` を受け取り、業務ルールは持たない（ADR-0009）。すべての読み取りは
``project_id`` を受け取ってそれで絞り込むので、他企画のコンテンツ id は存在しない
id と区別できない（design.md §5-2、F5）。論理削除済みの行は既定で除外する
（design.md §3-2）。
"""

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core.exceptions import VersionConflictError
from app.modules.contents.models import Content, ContentStatus, ContentStatusTransition


class ContentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, project_id: int, title: str, body_md: str, status: ContentStatus, created_by: int
    ) -> Content:
        content = Content(
            project_id=project_id,
            title=title,
            body_md=body_md,
            status=status.value,
            created_by=created_by,
        )
        self._session.add(content)
        await self.flush()
        return content

    async def get(self, content_id: int, project_id: int) -> Content | None:
        result = await self._session.execute(
            select(Content).where(
                Content.id == content_id,
                Content.project_id == project_id,
                Content.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list(self, project_id: int, status: ContentStatus | None = None) -> Sequence[Content]:
        """1企画の生きているコンテンツを新しい順に。status を渡せば1値だけに絞る。"""
        stmt = select(Content).where(Content.project_id == project_id, Content.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(Content.status == status.value)
        result = await self._session.execute(
            stmt.order_by(Content.created_at.desc(), Content.id.desc())
        )
        return result.scalars().all()

    async def soft_delete(self, content: Content) -> None:
        # created_at / updated_at と同じくサーバークロックを使う。ORM を経由させる
        # ことで、この UPDATE にも version チェックが伴うようにする。
        content.deleted_at = func.now()
        await self.flush()

    async def flush(self) -> None:
        """保留中の変更を flush し、楽観ロックの競合負けを 409 にマッピングする。

        ``version_id_col`` により、読み込み後に別トランザクションが version を
        進めていた場合、この UPDATE は0行にマッチする。SQLAlchemy はこれを
        ``StaleDataError`` として報告するので、ここで変換する（Service は
        ``sqlalchemy`` を import できないため。design.md §3-3、.importlinter）。
        """
        try:
            await self._session.flush()
        except StaleDataError as exc:
            raise VersionConflictError() from exc


class ContentTransitionRepository:
    """追記専用：行は追加されるだけで、更新・削除はされない（design.md §8-2）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        content_id: int,
        from_status: ContentStatus,
        to_status: ContentStatus,
        actor_user_id: int,
    ) -> ContentStatusTransition:
        row = ContentStatusTransition(
            content_id=content_id,
            from_status=from_status.value,
            to_status=to_status.value,
            actor_user_id=actor_user_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row
