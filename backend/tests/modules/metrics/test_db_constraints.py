"""metrics の主キー・部分 UNIQUE・CHECK・複合 FK のテスト（metrics design.md §3-4）。

Service を通さずに行を直接入れて、**DB の制約だけで**同日の二重記録・定期投入の二重化・
二重実行・負の値・企画をまたぐ参照が止まることを確かめる。Service 側の確認が漏れたときの最後の砦。
"""

from datetime import date

import pytest
from app.modules.auth.models import User
from app.modules.contents.models import Content, ContentStatus
from app.modules.metrics.models import (
    ItemStatus,
    JobKind,
    JobRun,
    JobRunItem,
    JobTrigger,
    MetricSnapshot,
    RunStatus,
    SnapshotSource,
)
from app.modules.projects.repository import ProjectRepository
from app.modules.publishing.models import Publication
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_user

TODAY = date(2026, 11, 3)


@pytest.fixture
async def author(db_session: AsyncSession) -> User:
    return await create_user(db_session, "author@example.com")


async def _publication(db_session: AsyncSession, author: User, name: str) -> Publication:
    project = await ProjectRepository(db_session).create(name=name, created_by=author.id)
    content = Content(
        project_id=project.id,
        title="ネタ",
        body_md="本文",
        status=ContentStatus.PUBLISHED.value,
        created_by=author.id,
    )
    db_session.add(content)
    await db_session.flush()
    publication = Publication(
        project_id=project.id,
        content_id=content.id,
        channel="qiita",
        external_id=f"item-{name}",
        url=f"https://qiita.com/u/items/item-{name}",
        published_by=author.id,
    )
    db_session.add(publication)
    await db_session.flush()
    return publication


@pytest.fixture
async def publication(db_session: AsyncSession, author: User) -> Publication:
    return await _publication(db_session, author, "こちら")


def _snapshot(publication: Publication, **kwargs: object) -> MetricSnapshot:
    values: dict[str, object] = {
        "publication_id": publication.id,
        "captured_on": TODAY,
        "project_id": publication.project_id,
        "channel": publication.channel,
        "source": SnapshotSource.AUTO.value,
        "likes": 3,
    }
    values.update(kwargs)
    return MetricSnapshot(**values)


def _run(project_id: int, trigger: JobTrigger, status: RunStatus, **kwargs: object) -> JobRun:
    values: dict[str, object] = {
        "project_id": project_id,
        "kind": JobKind.QIITA_METRICS.value,
        "trigger": trigger.value,
        "target_date": TODAY,
        "status": status.value,
    }
    values.update(kwargs)
    return JobRun(**values)


async def test_one_snapshot_per_publication_per_day(
    db_session: AsyncSession, publication: Publication
) -> None:
    db_session.add(_snapshot(publication))
    await db_session.flush()

    db_session.add(_snapshot(publication, likes=4))
    with pytest.raises(IntegrityError, match="metric_snapshots_pkey"):
        await db_session.flush()


async def test_another_day_is_a_separate_snapshot(
    db_session: AsyncSession, publication: Publication
) -> None:
    db_session.add(_snapshot(publication))
    db_session.add(_snapshot(publication, captured_on=date(2026, 11, 4)))
    await db_session.flush()


@pytest.mark.parametrize("column", ["views", "likes", "stocks", "comments"])
async def test_negative_metrics_are_rejected(
    db_session: AsyncSession, publication: Publication, column: str
) -> None:
    db_session.add(_snapshot(publication, **{column: -1}))
    with pytest.raises(IntegrityError, match=f"ck_metric_snapshots_{column}_nonneg"):
        await db_session.flush()


async def test_snapshot_cannot_point_at_another_projects_publication(
    db_session: AsyncSession, author: User, publication: Publication
) -> None:
    other = await _publication(db_session, author, "あちら")

    db_session.add(_snapshot(publication, project_id=other.project_id))
    with pytest.raises(IntegrityError, match="fk_metric_snapshots_publication"):
        await db_session.flush()


async def test_scheduled_run_is_inserted_once_per_day(
    db_session: AsyncSession, publication: Publication
) -> None:
    db_session.add(_run(publication.project_id, JobTrigger.SCHEDULED, RunStatus.SUCCEEDED))
    await db_session.flush()

    # 1件目が終わっていても、同じ日の定期投入は2件目を入れない
    db_session.add(_run(publication.project_id, JobTrigger.SCHEDULED, RunStatus.QUEUED))
    with pytest.raises(IntegrityError, match="uq_job_runs_scheduled_daily"):
        await db_session.flush()


async def test_manual_runs_on_the_same_day_are_allowed_once_finished(
    db_session: AsyncSession, publication: Publication
) -> None:
    db_session.add(_run(publication.project_id, JobTrigger.SCHEDULED, RunStatus.SUCCEEDED))
    db_session.add(_run(publication.project_id, JobTrigger.MANUAL, RunStatus.FAILED))
    db_session.add(_run(publication.project_id, JobTrigger.MANUAL, RunStatus.QUEUED))
    await db_session.flush()


@pytest.mark.parametrize("second", [RunStatus.QUEUED, RunStatus.RUNNING])
async def test_two_active_runs_of_the_same_kind_are_rejected(
    db_session: AsyncSession, publication: Publication, second: RunStatus
) -> None:
    db_session.add(_run(publication.project_id, JobTrigger.MANUAL, RunStatus.RUNNING))
    await db_session.flush()

    db_session.add(_run(publication.project_id, JobTrigger.MANUAL, second))
    with pytest.raises(IntegrityError, match="uq_job_runs_active"):
        await db_session.flush()


async def test_active_runs_of_different_kinds_coexist(
    db_session: AsyncSession, publication: Publication
) -> None:
    db_session.add(_run(publication.project_id, JobTrigger.MANUAL, RunStatus.RUNNING))
    db_session.add(
        _run(
            publication.project_id,
            JobTrigger.MANUAL,
            RunStatus.QUEUED,
            kind=JobKind.PODCAST_RSS.value,
        )
    )
    await db_session.flush()


async def test_item_cannot_point_at_another_projects_publication(
    db_session: AsyncSession, author: User, publication: Publication
) -> None:
    other = await _publication(db_session, author, "あちら")
    run = _run(publication.project_id, JobTrigger.MANUAL, RunStatus.QUEUED)
    db_session.add(run)
    await db_session.flush()

    db_session.add(
        JobRunItem(
            run_id=run.id,
            project_id=publication.project_id,
            publication_id=other.id,
            status=ItemStatus.QUEUED.value,
        )
    )
    with pytest.raises(IntegrityError, match="fk_job_run_items_publication"):
        await db_session.flush()


async def test_item_without_publication_is_allowed_for_rss(
    db_session: AsyncSession, publication: Publication
) -> None:
    run = _run(
        publication.project_id,
        JobTrigger.MANUAL,
        RunStatus.QUEUED,
        kind=JobKind.PODCAST_RSS.value,
    )
    db_session.add(run)
    await db_session.flush()

    db_session.add(
        JobRunItem(
            run_id=run.id,
            project_id=publication.project_id,
            publication_id=None,
            status=ItemStatus.QUEUED.value,
        )
    )
    await db_session.flush()
