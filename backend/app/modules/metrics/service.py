"""metrics の業務ルールと認可（metrics design.md）。

HTTP のことは知らない（``fastapi`` は import しない）。外部 API の具体実装も知らず、
``ports.py`` の Protocol だけを受け取る（``.importlinter`` で強制）。
Service は flush までで、commit は呼び出し側（``get_session`` / ワーカー）が持つ。
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime

from app.channels.capabilities import CAPABILITIES, METRIC_COLUMNS, ChannelCode
from app.core.authorization import Actor, Permission, ProjectAuthorizer
from app.core.clock import jst_date
from app.core.exceptions import (
    InvalidMetricError,
    InvalidSnapshotError,
    MetricsNotManualError,
    NotFoundError,
)
from app.modules.metrics.models import MetricSnapshot, SnapshotSource
from app.modules.metrics.ports import MetricValues, PublicationGateway
from app.modules.metrics.repository import SnapshotRepository
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
