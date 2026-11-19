"""metrics の DB アクセス（metrics design.md §3）。

業務ルールは持たない（ADR-0009）。公開物が企画に属しているかは、Service が先に
``PublicationGateway`` で確かめる。
"""

from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.capabilities import METRIC_COLUMNS, ChannelCode
from app.core.exceptions import JobInProgressError
from app.modules.metrics.models import (
    ItemStatus,
    JobKind,
    JobRun,
    JobRunItem,
    JobTrigger,
    MetricSnapshot,
    PodcastFeed,
    RunStatus,
    SnapshotSource,
)
from app.modules.metrics.ports import MetricValues
from app.modules.publishing.models import Publication


class SnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        publication: Publication,
        captured_on: date,
        values: MetricValues,
        source: SnapshotSource,
        updated_by: int | None,
    ) -> MetricSnapshot:
        """公開物×日で1行。同じ日は上書きする（ADR-0008）。

        4列すべてを書き直す。``values`` に無い列は NULL になる（前の値を残さない。
        残すと、どの値がいつのものか分からなくなる）。
        """
        metrics = {c: values.get(c) for c in METRIC_COLUMNS}
        values_stmt = insert(MetricSnapshot).values(
            publication_id=publication.id,
            captured_on=captured_on,
            project_id=publication.project_id,
            channel=publication.channel,
            source=source.value,
            updated_by=updated_by,
            **metrics,
        )
        stmt = values_stmt.on_conflict_do_update(
            index_elements=[MetricSnapshot.publication_id, MetricSnapshot.captured_on],
            set_={
                **{c: values_stmt.excluded[c] for c in METRIC_COLUMNS},
                "source": values_stmt.excluded.source,
                "updated_by": values_stmt.excluded.updated_by,
                "captured_at": func.now(),
            },
        ).returning(MetricSnapshot)
        # 同じセッションに古い行が載っていても、返ってきた値で上書きする。
        result = await self._session.scalars(stmt, execution_options={"populate_existing": True})
        return result.one()

    async def list_for_publication(self, publication_id: int) -> Sequence[MetricSnapshot]:
        """公開物の推移（古い順）。"""
        result = await self._session.scalars(
            select(MetricSnapshot)
            .where(MetricSnapshot.publication_id == publication_id)
            .order_by(MetricSnapshot.captured_on)
        )
        return result.all()


class JobRepository:
    """job_runs / job_run_items の読み書きと、キューの拾い方（design.md §6-1）。

    投入の対象（取り消されていない公開物・RSS を持つ企画）は ``publications`` /
    ``podcast_feeds`` を**読むだけ**で決める（design.md §2）。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- 投入 ---

    async def create_run(
        self,
        *,
        project_id: int,
        kind: JobKind,
        trigger: JobTrigger,
        target_date: date,
        requested_by: int | None,
        retry_of: int | None = None,
    ) -> JobRun:
        """手動実行・再実行。同じ企画×種類が待機中・実行中なら 409。"""
        run = JobRun(
            project_id=project_id,
            kind=kind.value,
            trigger=trigger.value,
            target_date=target_date,
            status=RunStatus.QUEUED.value,
            requested_by=requested_by,
            retry_of=retry_of,
        )
        try:
            # 失敗しても外側のトランザクションを生かす（SAVEPOINT）
            async with self._session.begin_nested():
                self._session.add(run)
                await self._session.flush()
        except IntegrityError as exc:
            if "uq_job_runs_active" in str(exc.orig):
                raise JobInProgressError() from exc
            raise
        return run

    async def insert_scheduled(
        self, *, project_id: int, kind: JobKind, target_date: date
    ) -> JobRun | None:
        """定期投入。今日の分がある・同じ種類が実行中なら何もせず None（design.md §6-3）。

        ``ON CONFLICT DO NOTHING`` に対象を書かないので、部分 UNIQUE 2本のどちらに
        当たっても入らない。プロセスが複数あっても1日1回になる。
        """
        stmt = (
            insert(JobRun)
            .values(
                project_id=project_id,
                kind=kind.value,
                trigger=JobTrigger.SCHEDULED.value,
                target_date=target_date,
                status=RunStatus.QUEUED.value,
            )
            .on_conflict_do_nothing()
            .returning(JobRun)
        )
        result = await self._session.scalars(stmt)
        return result.one_or_none()

    async def add_items(
        self, run: JobRun, publication_ids: Sequence[int | None], now: datetime
    ) -> None:
        """run に item を足し、``total`` を合わせる。0件なら run をその場で成功にする。"""
        self._session.add_all(
            JobRunItem(
                run_id=run.id,
                project_id=run.project_id,
                publication_id=publication_id,
                status=ItemStatus.QUEUED.value,
                next_run_at=now,
            )
            for publication_id in publication_ids
        )
        run.total = len(publication_ids)
        if not publication_ids:
            run.status = RunStatus.SUCCEEDED.value
            run.started_at = run.finished_at = now
        await self._session.flush()

    async def collectable_publication_ids(
        self, project_id: int, channels: Sequence[ChannelCode]
    ) -> list[int]:
        """指標を自動で取る公開物（取り消していないもの）。"""
        result = await self._session.scalars(
            select(Publication.id)
            .where(
                Publication.project_id == project_id,
                Publication.channel.in_([c.value for c in channels]),
                Publication.cancelled_at.is_(None),
            )
            .order_by(Publication.id)
        )
        return list(result.all())

    async def projects_with_collectable(self, channels: Sequence[ChannelCode]) -> list[int]:
        result = await self._session.scalars(
            select(Publication.project_id)
            .where(
                Publication.channel.in_([c.value for c in channels]),
                Publication.cancelled_at.is_(None),
            )
            .distinct()
            .order_by(Publication.project_id)
        )
        return list(result.all())

    async def projects_with_feed(self) -> list[int]:
        result = await self._session.scalars(
            select(PodcastFeed.project_id).order_by(PodcastFeed.project_id)
        )
        return list(result.all())

    async def has_feed(self, project_id: int) -> bool:
        found = await self._session.scalar(
            select(PodcastFeed.id).where(PodcastFeed.project_id == project_id)
        )
        return found is not None

    # --- 読み取り ---

    async def get_run(self, run_id: int, project_id: int) -> JobRun | None:
        result = await self._session.scalars(
            select(JobRun).where(JobRun.id == run_id, JobRun.project_id == project_id)
        )
        return result.one_or_none()

    async def lock_run(self, run_id: int) -> JobRun:
        """件数を足す前に run の行を押さえる（別プロセスと同時に確定しても数がずれない）。"""
        result = await self._session.scalars(
            select(JobRun)
            .where(JobRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.one()

    async def get_item(self, item_id: int) -> JobRunItem:
        item = await self._session.get(JobRunItem, item_id, populate_existing=True)
        if item is None:
            raise LookupError(f"job_run_item {item_id} not found")
        return item

    async def items_of(self, run_id: int) -> Sequence[JobRunItem]:
        result = await self._session.scalars(
            select(JobRunItem).where(JobRunItem.run_id == run_id).order_by(JobRunItem.id)
        )
        return result.all()

    async def failed_publication_ids(self, run_id: int) -> list[int | None]:
        result = await self._session.scalars(
            select(JobRunItem.publication_id)
            .where(JobRunItem.run_id == run_id, JobRunItem.status == ItemStatus.FAILED.value)
            .order_by(JobRunItem.id)
        )
        return list(result.all())

    # --- ワーカー ---

    async def claim_next(self, now: datetime) -> tuple[JobRunItem, JobRun] | None:
        """待機中で時刻が来た item を1件 running にする（``SKIP LOCKED``・design.md §6-1 ②）。"""
        item = (
            await self._session.scalars(
                select(JobRunItem)
                .where(
                    JobRunItem.status == ItemStatus.QUEUED.value,
                    JobRunItem.next_run_at <= now,
                )
                .order_by(JobRunItem.next_run_at, JobRunItem.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).one_or_none()
        if item is None:
            return None
        item.status = ItemStatus.RUNNING.value
        item.attempts += 1
        item.started_at = now
        run = await self.lock_run(item.run_id)
        if run.status == RunStatus.QUEUED.value:
            run.status = RunStatus.RUNNING.value
            run.started_at = now
        await self._session.flush()
        return item, run

    async def reap_stuck(self, started_before: datetime, now: datetime) -> int:
        """running のまま止まった item を queued に戻す。attempts はそのまま（§6-1 ①）。"""
        result = await self._session.execute(
            update(JobRunItem)
            .where(
                JobRunItem.status == ItemStatus.RUNNING.value,
                JobRunItem.started_at < started_before,
            )
            .values(
                status=ItemStatus.QUEUED.value,
                next_run_at=now,
                started_at=None,
                updated_at=func.now(),
            )
            .returning(JobRunItem.id)
        )
        return len(result.all())

    async def defer_queued(self, kind: JobKind, until: datetime) -> int:
        """同じ種類の待機中の item を ``until`` まで後ろにずらす（429・design.md §6-4）。"""
        result = await self._session.execute(
            update(JobRunItem)
            .where(
                JobRunItem.status == ItemStatus.QUEUED.value,
                JobRunItem.next_run_at < until,
                JobRunItem.run_id.in_(select(JobRun.id).where(JobRun.kind == kind.value)),
            )
            .values(next_run_at=until, updated_at=func.now())
            .returning(JobRunItem.id)
        )
        return len(result.all())

    async def flush(self) -> None:
        await self._session.flush()
