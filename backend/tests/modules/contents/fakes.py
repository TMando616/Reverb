"""contents の repository のインメモリダブル（design.md §13）。

``FakeContentRepository`` は、Service が依存している ``version_id_col`` の
挙動を1つだけ模している：``flush`` は追跡対象のフィールドが実際に変わった
ときだけ ``version`` を進める。本物の ``StaleDataError`` → 409 のマッピングは
2つの実トランザクションを要するので、ここでは ``lose_next_race`` で模擬し、
本物は tasks.md §7 の API 結合テストに委ねる。
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from app.core.exceptions import VersionConflictError
from app.modules.contents.models import Content, ContentStatus, ContentStatusTransition

_TRACKED = ("title", "body_md", "status", "deleted_at")


class FakeContentRepository:
    def __init__(self) -> None:
        self._rows: dict[int, Content] = {}
        self._snapshots: dict[int, tuple[object, ...]] = {}
        self._seq = 0
        self._lose_next_race = False

    async def create(
        self, *, project_id: int, title: str, body_md: str, status: ContentStatus, created_by: int
    ) -> Content:
        self._seq += 1
        now = datetime.now(UTC)
        content = Content(
            project_id=project_id,
            title=title,
            body_md=body_md,
            status=status.value,
            created_by=created_by,
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

    async def list(self, project_id: int, status: ContentStatus | None = None) -> Sequence[Content]:
        return [
            c
            for c in reversed(self._rows.values())
            if c.project_id == project_id
            and c.deleted_at is None
            and (status is None or c.status == status.value)
        ]

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
