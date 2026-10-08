"""contents の repository のインメモリダブル（design.md §13）。

``FakeContentRepository`` は、Service が依存している ``version_id_col`` の
挙動を1つだけ模している：``flush`` は追跡対象のフィールドが実際に変わった
ときだけ ``version`` を進める。本物の ``StaleDataError`` → 409 のマッピングは
2つの実トランザクションを要するので、ここでは ``lose_next_race`` で模擬する。
本物の経路は ``tests/modules/contents/test_optimistic_lock_race.py`` が
実 DB に接続2本を張って確認している。
"""

import builtins
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from app.core.exceptions import VersionConflictError
from app.modules.contents.models import (
    Content,
    ContentRevision,
    ContentStatus,
    ContentStatusTransition,
    RevisionKind,
)
from app.modules.contents.repository import RevisionSummary
from sqlalchemy.orm.attributes import set_committed_value

_TRACKED = ("title", "body_md", "status", "deleted_at", "source_note_path")


class FakeContentRepository:
    def __init__(self) -> None:
        self._rows: dict[int, Content] = {}
        self._snapshots: dict[int, tuple[object, ...]] = {}
        self._seq = 0
        self._lose_next_race = False

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
        self._seq += 1
        now = datetime.now(UTC)
        content = Content(
            project_id=project_id,
            title=title,
            body_md=body_md,
            status=status.value,
            created_by=created_by,
            source_note_path=source_note_path,
        )
        content.id = self._seq
        content.version = 1
        content.deleted_at = None
        content.created_at = content.updated_at = now
        self._rows[content.id] = content
        self._snapshots[content.id] = self._snapshot(content)
        return content

    async def get(self, content_id: int, project_id: int) -> Content | None:
        content = self._rows.get(content_id)
        if content is None or content.project_id != project_id or content.deleted_at is not None:
            return None
        return content

    async def list(
        self,
        project_id: int,
        statuses: Iterable[ContentStatus] = (),
        tag_ids: Iterable[int] = (),
        q: str | None = None,
    ) -> Sequence[Content]:
        # タグ・キーワードの絞り込みは本物の SQL でしか確かめない
        # （test_content_repository.py）。fake は状態だけ真似る。
        wanted = {s.value for s in statuses}
        return [
            c
            for c in reversed(self._rows.values())
            if c.project_id == project_id
            and c.deleted_at is None
            and (not wanted or c.status in wanted)
        ]

    async def reload_tags(self, content: Content) -> None:
        # タグの中身は fake では扱わない。レスポンス変換で落ちないよう空にしておく。
        set_committed_value(content, "tags", [])

    async def soft_delete(self, content: Content) -> None:
        content.deleted_at = datetime.now(UTC)
        await self.flush()

    async def flush(self) -> None:
        if self._lose_next_race:
            self._lose_next_race = False
            raise VersionConflictError()
        for content in self._rows.values():
            snapshot = self._snapshot(content)
            if snapshot != self._snapshots[content.id]:
                content.version += 1
                self._snapshots[content.id] = snapshot

    def lose_next_race(self) -> None:
        """次の flush を、別トランザクションが ``version`` を進めた場合と同じ挙動にする。"""
        self._lose_next_race = True

    @staticmethod
    def _snapshot(content: Content) -> tuple[object, ...]:
        return tuple(getattr(content, name) for name in _TRACKED)


class FakeContentTransitionRepository:
    def __init__(self) -> None:
        self.rows: list[ContentStatusTransition] = []

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
        row.id = len(self.rows) + 1
        self.rows.append(row)
        return row


class FakeTagRepository:
    """タグの存在確認だけを真似る。タグ自体の振る舞いは実 DB のテストで見る。"""

    def __init__(self, tags: Iterable[tuple[int, int]] = ()) -> None:
        # (project_id, tag_id) の組
        self._tags = set(tags)

    async def existing_ids(self, project_id: int, tag_ids: Iterable[int]) -> set[int]:
        return {t for t in tag_ids if (project_id, t) in self._tags}


class FakeContentTagRepository:
    def __init__(self) -> None:
        self.rows: set[tuple[int, int]] = set()  # (content_id, tag_id)

    async def tag_ids_of(self, content_id: int) -> set[int]:
        return {t for c, t in self.rows if c == content_id}

    async def add(self, *, project_id: int, content_id: int, tag_ids: Iterable[int]) -> None:
        self.rows |= {(content_id, t) for t in tag_ids}

    async def remove(self, *, content_id: int, tag_ids: Iterable[int]) -> None:
        self.rows -= {(content_id, t) for t in tag_ids}


class FakeRevisionRepository:
    # メソッド名 list が組み込みの list を隠すので、型注釈では builtins.list と書く。
    def __init__(self) -> None:
        self.rows: builtins.list[ContentRevision] = []

    async def append(
        self,
        content: Content,
        *,
        kind: RevisionKind,
        actor_user_id: int,
        restored_from_no: int | None = None,
    ) -> ContentRevision:
        revision = ContentRevision(
            content_id=content.id,
            revision_no=len(self.of(content.id)) + 1,
            title=content.title,
            body_md=content.body_md,
            kind=kind.value,
            restored_from_no=restored_from_no,
            created_by=actor_user_id,
        )
        revision.created_at = datetime.now(UTC)
        self.rows.append(revision)
        return revision

    async def list(
        self, content_id: int, *, before: int | None = None, limit: int = 50
    ) -> Sequence[RevisionSummary]:
        rows = [
            r for r in reversed(self.of(content_id)) if before is None or r.revision_no < before
        ]
        return [
            RevisionSummary(
                r.revision_no,
                r.title,
                r.kind,
                r.restored_from_no,
                r.created_by,
                r.created_at,
                len(r.body_md),
            )
            for r in rows[:limit]
        ]

    async def get(self, content_id: int, revision_no: int) -> ContentRevision | None:
        return next((r for r in self.of(content_id) if r.revision_no == revision_no), None)

    def of(self, content_id: int) -> builtins.list[ContentRevision]:
        return [r for r in self.rows if r.content_id == content_id]
