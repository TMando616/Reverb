"""metrics の実 DB テスト用の組み立て（metrics design.md §14）。

Repository は本物。時刻は固定の clock を差し込む。
"""

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from app.channels.capabilities import ChannelCode
from app.core.authorization import ProjectAuthorizer
from app.core.clock import JST
from app.modules.metrics.repository import SnapshotRepository
from app.modules.metrics.service import SnapshotService
from app.modules.projects.repository import ProjectMemberRepository
from app.modules.publishing.models import Publication
from app.modules.publishing.repository import PublicationRepository
from sqlalchemy.ext.asyncio import AsyncSession

# world フィクスチャを contents から借りる（conftest に import すると pytest が登録する）。
from tests.modules.contents.conftest import World, world  # noqa: F401

# 「今」は JST 2026-11-10 12:00。公開日は JST 2026-11-01 09:00。
NOW = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)
PUBLISHED_AT = datetime(2026, 11, 1, 9, 0, tzinfo=JST)


class FixedClock:
    """テストから「今」を動かせる時計。"""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@dataclass(frozen=True)
class Metrics:
    world: World
    snapshots: SnapshotService
    session: AsyncSession
    clock: FixedClock

    async def publication(
        self, channel: ChannelCode, *, project: int | None = None, title: str = "ネタ"
    ) -> Publication:
        """コンテンツと、そのチャネルの公開物を直接作る（公開の手順は publishing で確かめる）。"""
        project_id = project if project is not None else self.world.project
        content = await self.world.contents.create(
            self.world.owner, project_id, title=title, body_md="本文"
        )
        publication = await PublicationRepository(self.session).create(
            project_id=project_id,
            content_id=content.id,
            channel=channel,
            external_id=f"{channel.value}-{content.id}",
            url=f"https://example.com/{channel.value}/{content.id}",
            visibility=None,
            published_by=self.world.owner.user_id,
        )
        publication.published_at = PUBLISHED_AT
        await self.session.flush()
        return publication


@pytest.fixture
async def metrics(world: World, db_session: AsyncSession) -> Metrics:  # noqa: F811
    clock = FixedClock(NOW)
    return Metrics(
        world=world,
        snapshots=SnapshotService(
            snapshots=SnapshotRepository(db_session),
            publications=PublicationRepository(db_session),
            authz=ProjectAuthorizer(ProjectMemberRepository(db_session)),
            clock=clock,
        ),
        session=db_session,
        clock=clock,
    )
