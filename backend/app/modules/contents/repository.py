"""Persistence for the contents module — the only layer that talks to the DB.

Receives an ``AsyncSession``; holds no business rules (ADR-0009). Every read
takes ``project_id`` and filters on it, so a content id from another project is
indistinguishable from a missing one (design.md §5-2, F5). Soft-deleted rows are
excluded by default (design.md §3-2).
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
        """Live contents of one project, newest first, optionally one status only."""
        stmt = select(Content).where(Content.project_id == project_id, Content.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(Content.status == status.value)
        result = await self._session.execute(
            stmt.order_by(Content.created_at.desc(), Content.id.desc())
        )
        return result.scalars().all()

    async def soft_delete(self, content: Content) -> None:
        # Server clock, like created_at / updated_at. Goes through the ORM so the
        # UPDATE carries the version check too.
        content.deleted_at = func.now()
        await self.flush()

    async def flush(self) -> None:
        """Flush pending changes, mapping a lost optimistic-lock race to 409.

        ``version_id_col`` makes the UPDATE match zero rows when another
        transaction bumped ``version`` after we read it; SQLAlchemy reports that
        as ``StaleDataError``. It is translated here because the Service may not
        import ``sqlalchemy`` (design.md §3-3, .importlinter).
        """
        try:
            await self._session.flush()
        except StaleDataError as exc:
            raise VersionConflictError() from exc


class ContentTransitionRepository:
    """Append-only: rows are added, never updated or deleted (design.md §8-2)."""

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
