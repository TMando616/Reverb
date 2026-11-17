"""スナップショットの記録・手入力・推移のテスト（S1 / S7・metrics design.md §4・§5）。"""

from datetime import UTC, date, datetime

import pytest
from app.channels.capabilities import ChannelCode
from app.core.exceptions import (
    ForbiddenError,
    InvalidMetricError,
    InvalidSnapshotError,
    MetricsNotManualError,
    NotFoundError,
)
from app.modules.metrics.models import SnapshotSource

from tests.modules.metrics.conftest import Metrics

TODAY = date(2026, 11, 10)


# --- record_fetched（システム用の入口） ---


async def test_fetched_snapshot_is_overwritten_on_the_same_day(metrics: Metrics) -> None:
    pub = await metrics.publication(ChannelCode.QIITA)

    await metrics.snapshots.record_fetched(pub, TODAY, {"likes": 3, "stocks": 1, "views": 100})
    snap = await metrics.snapshots.record_fetched(pub, TODAY, {"likes": 5, "stocks": 2})

    assert (snap.likes, snap.stocks, snap.source, snap.updated_by) == (5, 2, "auto", None)
    # 2回目に無かった列は前の値を残さず NULL（閲覧数が取れなかった日・design.md §7-1）
    assert snap.views is None
    _, rows = await metrics.snapshots.list_for_publication(
        metrics.world.owner, metrics.world.project, pub.id
    )
    assert len(rows) == 1


async def test_fetched_rejects_a_manual_channel(metrics: Metrics) -> None:
    pub = await metrics.publication(ChannelCode.X)
    with pytest.raises(ValueError):
        await metrics.snapshots.record_fetched(pub, TODAY, {"views": 1})


async def test_fetched_rejects_a_metric_the_channel_does_not_have(metrics: Metrics) -> None:
    pub = await metrics.publication(ChannelCode.QIITA)
    # 指標の列名ですらない値（取得側の取り違え）
    with pytest.raises(ValueError):
        await metrics.snapshots.record_fetched(pub, TODAY, {"plays": 1})  # type: ignore[dict-item]


# --- input_manual ---


async def test_editor_inputs_and_overwrites_the_same_day(metrics: Metrics) -> None:
    w = metrics.world
    pub = await metrics.publication(ChannelCode.X)

    await metrics.snapshots.input_manual(w.editor, w.project, pub.id, TODAY, {"views": 10})
    snap = await metrics.snapshots.input_manual(
        w.owner, w.project, pub.id, TODAY, {"views": 12, "likes": 2}
    )

    assert (snap.views, snap.likes, snap.source) == (12, 2, SnapshotSource.MANUAL.value)
    assert snap.updated_by == w.owner.user_id
    _, rows = await metrics.snapshots.list_for_publication(w.owner, w.project, pub.id)
    assert [r.captured_on for r in rows] == [TODAY]


async def test_manual_input_to_an_auto_channel_is_rejected(metrics: Metrics) -> None:
    w = metrics.world
    pub = await metrics.publication(ChannelCode.QIITA)
    with pytest.raises(MetricsNotManualError):
        await metrics.snapshots.input_manual(w.owner, w.project, pub.id, TODAY, {"likes": 1})


async def test_metric_the_channel_does_not_have_is_rejected(metrics: Metrics) -> None:
    w = metrics.world
    pub = await metrics.publication(ChannelCode.PODCAST)
    # ポッドキャストは再生数（views）だけ
    with pytest.raises(InvalidMetricError):
        await metrics.snapshots.input_manual(w.owner, w.project, pub.id, TODAY, {"likes": 1})


@pytest.mark.parametrize(
    ("captured_on", "values"),
    [
        (date(2026, 11, 11), {"views": 1}),  # 未来
        (date(2026, 10, 31), {"views": 1}),  # 公開日より前
        (TODAY, {"views": -1}),  # 負の値
        (TODAY, {"views": None}),  # 値が1つも無い
        (TODAY, {}),
    ],
)
async def test_invalid_snapshot_is_rejected(
    metrics: Metrics, captured_on: date, values: dict[str, int | None]
) -> None:
    w = metrics.world
    pub = await metrics.publication(ChannelCode.X)
    with pytest.raises(InvalidSnapshotError):
        await metrics.snapshots.input_manual(w.owner, w.project, pub.id, captured_on, values)


async def test_publication_day_and_today_are_accepted_in_jst(metrics: Metrics) -> None:
    w = metrics.world
    pub = await metrics.publication(ChannelCode.X)
    # UTC では 11/10 15:30 だが、JST ではもう 11/11
    metrics.clock.now = datetime(2026, 11, 10, 15, 30, tzinfo=UTC)

    await metrics.snapshots.input_manual(
        w.owner, w.project, pub.id, date(2026, 11, 1), {"views": 1}
    )
    await metrics.snapshots.input_manual(
        w.owner, w.project, pub.id, date(2026, 11, 11), {"views": 2}
    )


@pytest.mark.parametrize("who", ["reviewer", "demo"])
async def test_reviewer_and_demo_cannot_input(metrics: Metrics, who: str) -> None:
    w = metrics.world
    pub = await metrics.publication(ChannelCode.X)
    with pytest.raises(ForbiddenError):
        await metrics.snapshots.input_manual(
            getattr(w, who), w.project, pub.id, TODAY, {"views": 1}
        )


async def test_publication_of_another_project_is_not_found(metrics: Metrics) -> None:
    w = metrics.world
    other = await metrics.publication(ChannelCode.X, project=w.other_project)

    with pytest.raises(NotFoundError):
        await metrics.snapshots.input_manual(w.owner, w.project, other.id, TODAY, {"views": 1})
    with pytest.raises(NotFoundError):
        await metrics.snapshots.list_for_publication(w.owner, w.project, other.id)


# --- list_for_publication ---


@pytest.mark.parametrize("who", ["reviewer", "demo"])
async def test_viewers_can_read_the_history(metrics: Metrics, who: str) -> None:
    w = metrics.world
    pub = await metrics.publication(ChannelCode.QIITA)
    await metrics.snapshots.record_fetched(pub, date(2026, 11, 3), {"likes": 1})
    await metrics.snapshots.record_fetched(pub, date(2026, 11, 2), {"likes": 0})

    _, rows = await metrics.snapshots.list_for_publication(getattr(w, who), w.project, pub.id)
    assert [r.captured_on for r in rows] == [date(2026, 11, 2), date(2026, 11, 3)]


async def test_cancelled_publication_history_is_still_readable(metrics: Metrics) -> None:
    w = metrics.world
    pub = await metrics.publication(ChannelCode.QIITA)
    await metrics.snapshots.record_fetched(pub, TODAY, {"likes": 4})
    pub.cancelled_at = metrics.clock.now
    pub.cancelled_by = w.owner.user_id
    await metrics.session.flush()

    got, rows = await metrics.snapshots.list_for_publication(w.owner, w.project, pub.id)
    assert got.cancelled_at is not None
    assert [r.likes for r in rows] == [4]
