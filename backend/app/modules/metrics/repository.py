"""metrics の DB アクセス（metrics design.md §3）。

業務ルールは持たない（ADR-0009）。公開物が企画に属しているかは、Service が先に
``PublicationGateway`` で確かめる。
"""

from collections.abc import Sequence
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.capabilities import METRIC_COLUMNS
from app.modules.metrics.models import MetricSnapshot, SnapshotSource
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
