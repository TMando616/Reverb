"""Business rules and authorization for the contents module (コンテンツ CRUD・状態遷移).

Knows nothing about HTTP (no ``fastapi`` / ``Request``) and never holds an
``AsyncSession`` directly — repositories are injected in (design.md §2-2).
Authorization is the first line of every method so MCP / job callers get the
same checks as the browser (design.md §5-2, F5).
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
        """New contents always start in ``inbox`` (F6)."""
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
        """Update title and/or body under the two-stage optimistic lock (design.md §3-3).

        Stage 1 compares ``expected_version`` with what we just read, so a client
        that was already stale gets a clear 409 before anything is written. Stage 2
        is the ``WHERE version = ?`` on flush, which catches a writer that slipped
        in between our read and our flush; the repository maps it to the same 409.

        Sending unchanged values issues no UPDATE and leaves ``version`` as is.
        That is intended: nothing changed, so no other client's copy went stale.
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
        """Logical delete (design.md §3-2); later specs keep referring to the row."""
        await self._authz.require(actor, project_id, Permission.CONTENT_WRITE)
        content = await self._get_or_404(content_id, project_id)
        await self._contents.soft_delete(content)

    async def _get_or_404(self, content_id: int, project_id: int) -> Content:
        # Scoped by project_id: another project's content id is just "not found".
        content = await self._contents.get(content_id, project_id)
        if content is None:
            raise NotFoundError("content")
        return content

    @staticmethod
    def _check_version(content: Content, expected_version: int) -> None:
        if content.version != expected_version:
            raise VersionConflictError()
