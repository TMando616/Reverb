"""metrics の業務ルールと認可（metrics design.md）。

HTTP のことは知らない（``fastapi`` は import しない）。外部 API の具体実装も知らず、
``ports.py`` の Protocol だけを受け取る（``.importlinter`` で強制）。
Service は flush までで、commit は呼び出し側（``get_session`` / ワーカー）が持つ。
"""

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from app.channels.capabilities import CAPABILITIES, METRIC_COLUMNS, ChannelCode
from app.core.authorization import Actor, Permission, ProjectAuthorizer
from app.core.clock import JST, jst_date
from app.core.exceptions import (
    InvalidMetricError,
    InvalidSnapshotError,
    MetricsNotManualError,
    NotFoundError,
    NothingToRetryError,
)
from app.modules.metrics.models import (
    ACTIVE_RUN_STATUSES,
    ItemStatus,
    JobKind,
    JobRun,
    JobRunItem,
    JobTrigger,
    MetricSnapshot,
    RunStatus,
    SnapshotSource,
)
from app.modules.metrics.ports import JobFailed, MetricValues, PublicationGateway
from app.modules.metrics.repository import JobRepository, SnapshotRepository
from app.modules.publishing.models import Publication


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SnapshotService:
    """スナップショットの記録・手入力・推移（S1 / S7・design.md §4・§5）。"""

    def __init__(
        self,
        *,
        snapshots: SnapshotRepository,
        publications: PublicationGateway,
        authz: ProjectAuthorizer,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._snapshots = snapshots
        self._publications = publications
        self._authz = authz
        self._clock = clock

    async def record_fetched(
        self, publication: Publication, captured_on: date, values: MetricValues
    ) -> MetricSnapshot:
        """自動取得した値を書く。**システム用の入口で、認可を通らない**（design.md §5-2）。

        ワーカーだけが呼ぶ。router には出さない。投入時に ``METRICS_COLLECT`` を確認済みか、
        定期実行（操作した人がいない）のどちらか。
        """
        caps = CAPABILITIES[ChannelCode(publication.channel)]
        if caps.metrics != "auto":
            # ワーカーの取り違え。手入力の値を自動取得で潰さない
            raise ValueError(f"channel {publication.channel} is not collected automatically")
        unknown = set(values) - set(caps.metric_columns())
        if unknown:
            raise ValueError(f"unknown metrics for {publication.channel}: {sorted(unknown)}")
        return await self._snapshots.upsert(
            publication=publication,
            captured_on=captured_on,
            values=values,
            source=SnapshotSource.AUTO,
            updated_by=None,
        )

    async def input_manual(
        self,
        actor: Actor,
        project_id: int,
        publication_id: int,
        captured_on: date,
        values: Mapping[str, int | None],
    ) -> MetricSnapshot:
        """手入力（上書き）。``metrics = manual`` のチャネルだけ（S7）。"""
        await self._authz.require(actor, project_id, Permission.METRICS_INPUT)
        publication = await self._get(project_id, publication_id)

        caps = CAPABILITIES[ChannelCode(publication.channel)]
        if caps.metrics != "manual":
            raise MetricsNotManualError()
        allowed = set(caps.metric_columns())
        if any(column not in allowed for column in values):
            raise InvalidMetricError()
        if all(v is None for v in values.values()):
            raise InvalidSnapshotError("at least one metric is required")
        if any(v is not None and v < 0 for v in values.values()):
            raise InvalidSnapshotError("metrics must not be negative")
        if captured_on > jst_date(self._clock()):
            raise InvalidSnapshotError("captured_on must not be in the future")
        if captured_on < jst_date(publication.published_at):
            raise InvalidSnapshotError("captured_on must not be before the publication")

        # allowed で絞ったので、キーは指標の列名だけになっている
        metrics = {c: values[c] for c in METRIC_COLUMNS if c in values}
        return await self._snapshots.upsert(
            publication=publication,
            captured_on=captured_on,
            values=metrics,
            source=SnapshotSource.MANUAL,
            updated_by=actor.user_id,
        )

    async def list_for_publication(
        self, actor: Actor, project_id: int, publication_id: int
    ) -> tuple[Publication, Sequence[MetricSnapshot]]:
        """公開物と、その推移（古い順）。取り消した公開物も読める。"""
        await self._authz.require(actor, project_id, Permission.PROJECT_VIEW)
        publication = await self._get(project_id, publication_id)
        return publication, await self._snapshots.list_for_publication(publication.id)

    async def _get(self, project_id: int, publication_id: int) -> Publication:
        # 他企画の公開物は「無い」と同じに見せる（存在を漏らさない）
        publication = await self._publications.get_in_project(publication_id, project_id)
        if publication is None:
            raise NotFoundError("publication")
        return publication


# --- ジョブ（design.md §6） ---

MAX_ATTEMPTS = 5
# 1分・4分・16分・64分（design.md §6-2）
RETRY_BASE = timedelta(minutes=1)
RETRY_FACTOR = 4
# Rate-Reset が無い 429
RATE_LIMIT_FALLBACK = timedelta(minutes=15)
# 1件は数秒（タイムアウト15秒）なので、生きている実行を回収しない長さ
STUCK_AFTER = timedelta(minutes=10)
# 前日の反応が出そろってから取る（design.md §6-3）
SCHEDULE_FROM = time(5, 0)

AUTO_CHANNELS: tuple[ChannelCode, ...] = tuple(
    code for code, caps in CAPABILITIES.items() if caps.metrics == "auto"
)


def _jitter() -> float:
    """±20% の揺らぎ。同じ時刻に失敗した item が同じ時刻に揃って再試行しないように。"""
    return random.uniform(0.8, 1.2)


def retry_delay(attempts: int, jitter: float) -> timedelta:
    """``attempts`` 回目が失敗したあと、次を試すまでの間隔。"""
    factor: int = RETRY_FACTOR ** (attempts - 1)
    return RETRY_BASE * factor * jitter


@dataclass(frozen=True, slots=True)
class ClaimedItem:
    """ワーカーが DB の外へ持ち出す1件分。ORM の行は持ち出さない（セッションを閉じるので）。"""

    item_id: int
    run_id: int
    project_id: int
    kind: JobKind
    publication_id: int | None
    target_date: date
    attempts: int
    requested_by: int | None


class JobService:
    """ジョブの投入・拾う・確定（S2 / S3 / S4・design.md §6）。

    ``request_run`` / ``retry`` は人の操作で、``METRICS_COLLECT`` を確認する。
    ``claim`` / ``succeed`` / ``fail`` / ``reap_stuck`` / ``schedule_daily`` は
    ワーカーと scheduler だけが呼ぶシステム用の入口で、router には出さない。
    """

    def __init__(
        self,
        *,
        jobs: JobRepository,
        authz: ProjectAuthorizer,
        clock: Callable[[], datetime] = _utcnow,
        jitter: Callable[[], float] = _jitter,
    ) -> None:
        self._jobs = jobs
        self._authz = authz
        self._clock = clock
        self._jitter = jitter

    # --- 人の操作 ---

    async def request_run(self, actor: Actor, project_id: int, kind: JobKind) -> JobRun:
        """手動実行。同じ企画×種類が待機中・実行中なら 409（S4）。"""
        await self._authz.require(actor, project_id, Permission.METRICS_COLLECT)
        targets = await self._targets(project_id, kind)
        now = self._clock()
        run = await self._jobs.create_run(
            project_id=project_id,
            kind=kind,
            trigger=JobTrigger.MANUAL,
            target_date=jst_date(now),
            requested_by=actor.user_id,
        )
        await self._jobs.add_items(run, targets, now)
        return run

    async def retry(self, actor: Actor, project_id: int, run_id: int) -> JobRun:
        """失敗した item だけで新しい run を作る。元の run は書き換えない（S4）。"""
        await self._authz.require(actor, project_id, Permission.METRICS_COLLECT)
        original = await self._jobs.get_run(run_id, project_id)
        if original is None:
            raise NotFoundError("job run")
        failed = await self._jobs.failed_publication_ids(original.id)
        if not failed:
            raise NothingToRetryError()
        now = self._clock()
        run = await self._jobs.create_run(
            project_id=project_id,
            kind=JobKind(original.kind),
            trigger=JobTrigger.RETRY,
            # 再実行も「今日」の値として取る（外部 API は今の値しか返さない）
            target_date=jst_date(now),
            requested_by=actor.user_id,
            retry_of=original.id,
        )
        await self._jobs.add_items(run, failed, now)
        return run

    async def _targets(self, project_id: int, kind: JobKind) -> list[int | None]:
        if kind is JobKind.QIITA_METRICS:
            return list(await self._jobs.collectable_publication_ids(project_id, AUTO_CHANNELS))
        if not await self._jobs.has_feed(project_id):
            raise NotFoundError("podcast feed")
        # RSS は取得1回で1件（公開物はまだ無い）
        return [None]

    # --- scheduler ---

    async def schedule_daily(self) -> int:
        """JST 05:00 以降なら、今日の定期実行を企画×種類ごとに1回だけ入れる（design.md §6-3）。

        今日の分がある・手動実行が走っている企画は飛ばす（後者は次の tick で入る）。
        前日以前の分はさかのぼらない。入れた run の数を返す。
        """
        now = self._clock()
        if now.astimezone(JST).time() < SCHEDULE_FROM:
            return 0
        today = jst_date(now)
        inserted = 0
        plans: list[tuple[JobKind, list[int]]] = [
            (JobKind.QIITA_METRICS, await self._jobs.projects_with_collectable(AUTO_CHANNELS)),
            (JobKind.PODCAST_RSS, await self._jobs.projects_with_feed()),
        ]
        for kind, project_ids in plans:
            for project_id in project_ids:
                run = await self._jobs.insert_scheduled(
                    project_id=project_id, kind=kind, target_date=today
                )
                if run is None:
                    continue
                await self._jobs.add_items(run, await self._targets(project_id, kind), now)
                inserted += 1
        return inserted

    # --- ワーカー ---

    async def reap_stuck(self) -> int:
        now = self._clock()
        return await self._jobs.reap_stuck(now - STUCK_AFTER, now)

    async def claim(self) -> ClaimedItem | None:
        claimed = await self._jobs.claim_next(self._clock())
        if claimed is None:
            return None
        item, run = claimed
        return ClaimedItem(
            item_id=item.id,
            run_id=run.id,
            project_id=run.project_id,
            kind=JobKind(run.kind),
            publication_id=item.publication_id,
            target_date=run.target_date,
            attempts=item.attempts,
            requested_by=run.requested_by,
        )

    async def succeed(self, item_id: int) -> bool:
        """item を成功にする。もう running でなければ何もせず False（下の ``_running``）。"""
        item = await self._running(item_id)
        if item is None:
            return False
        self._finish(item, ItemStatus.SUCCEEDED)
        run = await self._jobs.lock_run(item.run_id)
        run.succeeded += 1
        self._settle(run)
        await self._jobs.flush()
        return True

    async def fail(self, item_id: int, failure: JobFailed) -> bool:
        """リトライか確定失敗かを決める（design.md §6-2）。running でなければ False。"""
        now = self._clock()
        item = await self._running(item_id)
        if item is None:
            return False
        item.error_code = failure.error_code
        item.error_message = failure.message

        if failure.rate_limited:
            # 制限は失敗ではない。数えた分を戻し、同じ種類の残りもまとめて後ろへ
            until = failure.reset_at or now + RATE_LIMIT_FALLBACK
            item.attempts = max(item.attempts - 1, 0)
            self._requeue(item, until)
            run = await self._jobs.lock_run(item.run_id)
            await self._jobs.flush()
            await self._jobs.defer_queued(JobKind(run.kind), until)
            return True

        if failure.retryable and item.attempts < MAX_ATTEMPTS:
            self._requeue(item, now + retry_delay(item.attempts, self._jitter()))
            await self._jobs.flush()
            return True

        self._finish(item, ItemStatus.FAILED)
        run = await self._jobs.lock_run(item.run_id)
        run.failed += 1
        self._settle(run)
        await self._jobs.flush()
        return True

    async def _running(self, item_id: int) -> JobRunItem | None:
        """結果を書く item。回収されて queued に戻ったあとに遅れて結果が来たときは None。

        そのまま書くと、拾い直した実行と件数を二重に足すことになる。
        """
        item = await self._jobs.get_item(item_id)
        return item if item.status == ItemStatus.RUNNING.value else None

    def _requeue(self, item: JobRunItem, at: datetime) -> None:
        item.status = ItemStatus.QUEUED.value
        item.next_run_at = at
        item.started_at = None

    def _finish(self, item: JobRunItem, status: ItemStatus) -> None:
        item.status = status.value
        item.finished_at = self._clock()
        if status is ItemStatus.SUCCEEDED:
            item.error_code = item.error_message = None

    def _settle(self, run: JobRun) -> None:
        """全 item が確定したら run の最終状態を決める。"""
        if run.succeeded + run.failed < run.total:
            return
        if run.failed == 0:
            run.status = RunStatus.SUCCEEDED.value
        elif run.succeeded == 0:
            run.status = RunStatus.FAILED.value
        else:
            run.status = RunStatus.PARTIALLY_FAILED.value
        run.finished_at = self._clock()

    # --- 読み取り（§6 の API で使う） ---

    async def get_run(
        self, actor: Actor, project_id: int, run_id: int
    ) -> tuple[JobRun, Sequence[JobRunItem]]:
        await self._authz.require(actor, project_id, Permission.PROJECT_VIEW)
        run = await self._jobs.get_run(run_id, project_id)
        if run is None:
            raise NotFoundError("job run")
        return run, await self._jobs.items_of(run.id)

    @staticmethod
    def is_active(run: JobRun) -> bool:
        return RunStatus(run.status) in ACTIVE_RUN_STATUSES
