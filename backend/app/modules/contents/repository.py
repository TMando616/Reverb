"""contents モジュールの永続化 ── DB を叩く唯一の層。

``AsyncSession`` を受け取り、業務ルールは持たない（ADR-0009）。すべての読み取りは
``project_id`` を受け取ってそれで絞り込むので、他企画のコンテンツ id は存在しない
id と区別できない（design.md §5-2、F5）。論理削除済みの行は既定で除外する
（design.md §3-2）。
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, distinct, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.exc import StaleDataError

from app.core.exceptions import TagNameConflictError, VersionConflictError
from app.modules.contents.models import (
    Content,
    ContentRevision,
    ContentStatus,
    ContentStatusTransition,
    ContentTag,
    RevisionKind,
    Tag,
)


async def _flush_mapping_conflicts(session: AsyncSession) -> None:
    """flush し、楽観ロックの競合負けを 409 にマッピングする。

    ``version_id_col`` により、読み込み後に別トランザクションが version を進めて
    いた場合、この UPDATE は0行にマッチする。SQLAlchemy はこれを ``StaleDataError``
    として報告するので、ここで変換する（Service は ``sqlalchemy`` を import できない
    ため。design.md §3-3、.importlinter）。
    """
    try:
        await session.flush()
    except StaleDataError as exc:
        raise VersionConflictError() from exc


def _escape_like(value: str) -> str:
    """LIKE のワイルドカード（``%`` ``_``）とエスケープ文字自体を文字として扱わせる。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ContentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: int,
        title: str,
        body_md: str,
        status: ContentStatus,
        created_by: int,
        source_note_path: str | None = None,
    ) -> Content:
        content = Content(
            project_id=project_id,
            title=title,
            body_md=body_md,
            status=status.value,
            created_by=created_by,
            source_note_path=source_note_path,
        )
        self._session.add(content)
        await self.flush()
        return content

    async def get(self, content_id: int, project_id: int) -> Content | None:
        """タグも一緒に読む（``Content.tags`` は ``lazy="raise"``・design.md §6-5）。"""
        result = await self._session.execute(
            select(Content)
            .where(
                Content.id == content_id,
                Content.project_id == project_id,
                Content.deleted_at.is_(None),
            )
            .options(selectinload(Content.tags))
        )
        return result.scalar_one_or_none()

    async def list(
        self,
        project_id: int,
        statuses: Iterable[ContentStatus] = (),
        tag_ids: Iterable[int] = (),
        q: str | None = None,
    ) -> Sequence[Content]:
        """1企画の生きているコンテンツを、最終更新の新しい順に（content-pipeline design.md §6-5）。

        条件はすべて AND。``tag_ids`` は「指定したタグを**すべて**持つ」もの、
        ``statuses`` はいずれかの状態、``q`` はタイトルか本文の部分一致。
        """
        stmt = select(Content).where(Content.project_id == project_id, Content.deleted_at.is_(None))
        status_values = [s.value for s in statuses]
        if status_values:
            stmt = stmt.where(Content.status.in_(status_values))
        wanted = set(tag_ids)
        if wanted:
            # タグを n 回 JOIN する代わりに、件数で「全部持っている」を判定する。
            # n が増えてもクエリの形が変わらない。
            having_all = (
                select(ContentTag.content_id)
                .where(ContentTag.project_id == project_id, ContentTag.tag_id.in_(wanted))
                .group_by(ContentTag.content_id)
                .having(func.count(distinct(ContentTag.tag_id)) == len(wanted))
            )
            stmt = stmt.where(Content.id.in_(having_all))
        if q:
            pattern = f"%{_escape_like(q)}%"
            stmt = stmt.where(
                or_(
                    Content.title.ilike(pattern, escape="\\"),
                    Content.body_md.ilike(pattern, escape="\\"),
                )
            )
        result = await self._session.execute(
            stmt.options(selectinload(Content.tags)).order_by(
                Content.updated_at.desc(), Content.id.desc()
            )
        )
        return result.scalars().all()

    async def reload_tags(self, content: Content) -> None:
        """タグの付け替え後・作成直後に ``content.tags`` を読み直す。

        ``tags`` は viewonly なので、``ContentTag`` を足し引きしても勝手には変わらない。
        """
        await self._session.refresh(content, attribute_names=["tags"])

    async def soft_delete(self, content: Content) -> None:
        # ORM を経由させることで、この UPDATE にも version チェックが伴う。
        # func.now() のような SQL 式を代入すると、flush 後もその属性は expired の
        # ままになり、次に読んだ側（ログ・レスポンス）で MissingGreenlet になる。
        content.deleted_at = datetime.now(UTC)
        await self.flush()

    async def flush(self) -> None:
        """保留中の変更を flush する（競合は 409 になる）。"""
        await _flush_mapping_conflicts(self._session)


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
        # 素の flush ではなく共通のラッパを通す。flush はセッション全体を書き出すので、
        # ここで他の dirty な行が楽観ロックに負けると StaleDataError が生で上がり、
        # 409 ではなく 500 になる。
        await _flush_mapping_conflicts(self._session)
        return row


class TagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_with_usage(self, project_id: int) -> Sequence[tuple[Tag, int]]:
        """企画のタグを名前順に、生きているコンテンツへの付与件数と一緒に返す。"""
        usage = (
            select(func.count(ContentTag.content_id))
            .join(Content, Content.id == ContentTag.content_id)
            .where(ContentTag.tag_id == Tag.id, Content.deleted_at.is_(None))
            .scalar_subquery()
        )
        result = await self._session.execute(
            select(Tag, usage).where(Tag.project_id == project_id).order_by(Tag.name, Tag.id)
        )
        return [(tag, count) for tag, count in result.tuples()]

    async def get(self, tag_id: int, project_id: int) -> Tag | None:
        result = await self._session.execute(
            select(Tag).where(Tag.id == tag_id, Tag.project_id == project_id)
        )
        return result.scalar_one_or_none()

    async def existing_ids(self, project_id: int, tag_ids: Iterable[int]) -> set[int]:
        """``tag_ids`` のうち、この企画に実在するものだけを返す。"""
        wanted = set(tag_ids)
        if not wanted:
            return set()
        result = await self._session.execute(
            select(Tag.id).where(Tag.project_id == project_id, Tag.id.in_(wanted))
        )
        return set(result.scalars().all())

    async def create(self, *, project_id: int, name: str, name_key: str) -> Tag:
        tag = Tag(project_id=project_id, name=name, name_key=name_key)
        try:
            async with self._session.begin_nested():
                self._session.add(tag)
                await self._session.flush()
        except IntegrityError as exc:
            raise TagNameConflictError() from exc
        return tag

    async def rename(self, tag: Tag, *, name: str, name_key: str) -> None:
        before = (tag.name, tag.name_key)
        try:
            async with self._session.begin_nested():
                tag.name, tag.name_key = name, name_key
                await self._session.flush()
        except IntegrityError as exc:
            # SAVEPOINT のロールバックで属性が expire される。async では後から読むと
            # 暗黙のロードになるので、元の値を戻しておく（DB 側も元のまま）。
            tag.name, tag.name_key = before
            raise TagNameConflictError() from exc

    async def delete(self, tag: Tag) -> None:
        # content_tags は FK の ON DELETE CASCADE で消える。
        await self._session.delete(tag)
        await self._session.flush()

    # UNIQUE (project_id, name_key) 違反は 409 にする。Service は事前に同名を確かめない
    # （確かめても INSERT までの間に別のリクエストが入れば同じことになる）。
    # **変更は必ず begin_nested() の中で行う。** begin_nested() は SAVEPOINT を張る前に
    # 保留中の変更を flush するので、外で add / 代入すると違反が SAVEPOINT の外で起き、
    # トランザクションごと使えなくなる。


class ContentTagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def tag_ids_of(self, content_id: int) -> set[int]:
        result = await self._session.execute(
            select(ContentTag.tag_id).where(ContentTag.content_id == content_id)
        )
        return set(result.scalars().all())

    async def add(self, *, project_id: int, content_id: int, tag_ids: Iterable[int]) -> None:
        self._session.add_all(
            ContentTag(project_id=project_id, content_id=content_id, tag_id=tag_id)
            for tag_id in tag_ids
        )
        await self._session.flush()

    async def remove(self, *, content_id: int, tag_ids: Iterable[int]) -> None:
        targets = set(tag_ids)
        if not targets:
            return
        await self._session.execute(
            delete(ContentTag).where(
                ContentTag.content_id == content_id, ContentTag.tag_id.in_(targets)
            )
        )


@dataclass(frozen=True, slots=True)
class RevisionSummary:
    """版の一覧の1行。本文は持たず、文字数だけ（content-pipeline design.md §6-1）。"""

    revision_no: int
    title: str
    kind: str
    restored_from_no: int | None
    created_by: int
    created_at: datetime
    body_length: int


class RevisionRepository:
    """追記専用：行は追加されるだけで、更新・削除はされない（C7）。

    すべての読み取りは ``content_id`` で絞る。コンテンツが企画に属しているかは
    Service が先に ``ContentRepository.get(content_id, project_id)`` で確かめる。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        content: Content,
        *,
        kind: RevisionKind,
        actor_user_id: int,
        restored_from_no: int | None = None,
    ) -> ContentRevision:
        """``content`` の今の title / body_md を次の版番号で残す。

        同じコンテンツへの並行保存は ``contents`` の楽観ロックで先に1つに絞られるので、
        ``MAX + 1`` が衝突することは通常ない。すり抜けたら UNIQUE が落とし、409 にする。
        """
        next_no = (
            await self._session.scalar(
                select(func.coalesce(func.max(ContentRevision.revision_no), 0)).where(
                    ContentRevision.content_id == content.id
                )
            )
            or 0
        ) + 1
        revision = ContentRevision(
            content_id=content.id,
            revision_no=next_no,
            title=content.title,
            body_md=content.body_md,
            kind=kind.value,
            restored_from_no=restored_from_no,
            created_by=actor_user_id,
        )
        try:
            # add は begin_nested() の中で行う（TagRepository の注記と同じ理由）。
            async with self._session.begin_nested():
                self._session.add(revision)
                await self._session.flush()
        except IntegrityError as exc:
            raise VersionConflictError() from exc
        return revision

    async def list(
        self, content_id: int, *, before: int | None = None, limit: int = 50
    ) -> Sequence[RevisionSummary]:
        """新しい順。``before`` を渡すと、その版番号より古いものから ``limit`` 件。"""
        stmt = select(
            ContentRevision.revision_no,
            ContentRevision.title,
            ContentRevision.kind,
            ContentRevision.restored_from_no,
            ContentRevision.created_by,
            ContentRevision.created_at,
            func.char_length(ContentRevision.body_md),
        ).where(ContentRevision.content_id == content_id)
        if before is not None:
            stmt = stmt.where(ContentRevision.revision_no < before)
        result = await self._session.execute(
            stmt.order_by(ContentRevision.revision_no.desc()).limit(limit)
        )
        return [RevisionSummary(*row) for row in result.tuples()]

    async def get(self, content_id: int, revision_no: int) -> ContentRevision | None:
        result = await self._session.execute(
            select(ContentRevision).where(
                ContentRevision.content_id == content_id,
                ContentRevision.revision_no == revision_no,
            )
        )
        return result.scalar_one_or_none()
