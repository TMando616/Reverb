"""チャネルの定義と capabilities（ADR-0005・publishing design.md §3-2）。

チャネルはテーブルに置かず、ここが正。capabilities は振る舞い（Qiita なら API を叩く）と
一体で、チャネルを足すにはどのみちアダプタのコードが要るため。
画面・Service は ``CAPABILITIES[channel]`` を見て分岐し、チャネル名で分岐しない（C1）。
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class ChannelCode(StrEnum):
    QIITA = "qiita"
    X = "x"
    NOTE = "note"
    PODCAST = "podcast"


PublishMode = Literal["auto", "intent", "manual"]
MetricsMode = Literal["auto", "manual", "none"]
Format = Literal["markdown", "text"]
# metric_snapshots の指標の列（ADR-0008）。列は汎用で、チャネルでの意味は MetricField.label が持つ。
MetricColumn = Literal["views", "likes", "stocks", "comments"]
METRIC_COLUMNS: tuple[MetricColumn, ...] = ("views", "likes", "stocks", "comments")


@dataclass(frozen=True)
class MetricField:
    column: MetricColumn
    label: str


@dataclass(frozen=True)
class Capabilities:
    label: str
    publish: PublishMode
    metrics: MetricsMode
    format: Format
    # このチャネルで意味のある指標の列。ここに無い列は常に NULL（metrics design.md §4）。
    metric_fields: tuple[MetricField, ...]
    # 分析でチャネル内を比べるときの代表指標（metrics design.md §9-1）。
    primary_metric: MetricColumn
    max_length: int | None = None

    def metric_columns(self) -> frozenset[MetricColumn]:
        return frozenset(f.column for f in self.metric_fields)


CAPABILITIES: dict[ChannelCode, Capabilities] = {
    ChannelCode.QIITA: Capabilities(
        label="Qiita",
        publish="auto",
        metrics="auto",
        format="markdown",
        # 閲覧数は取れない日がある（page_views_count が NULL）。取れなければ NULL のまま持つ。
        metric_fields=(
            MetricField("likes", "LGTM"),
            MetricField("stocks", "ストック"),
            MetricField("comments", "コメント"),
            MetricField("views", "閲覧数"),
        ),
        primary_metric="likes",
    ),
    # 以下の publish は M3 で使う。文字数の数え方（全角を2と数える等）は M3 着手時に確認する。
    ChannelCode.X: Capabilities(
        label="X",
        publish="intent",
        metrics="manual",
        format="text",
        metric_fields=(MetricField("views", "インプレッション"), MetricField("likes", "いいね")),
        primary_metric="views",
        max_length=280,
    ),
    ChannelCode.NOTE: Capabilities(
        label="note",
        publish="manual",
        metrics="manual",
        format="markdown",
        metric_fields=(
            MetricField("views", "ビュー"),
            MetricField("likes", "スキ"),
            MetricField("comments", "コメント"),
        ),
        primary_metric="likes",
    ),
    # 公開物は RSS で自動登録するが、指標（再生数）は手入力（metrics design.md §4）。
    ChannelCode.PODCAST: Capabilities(
        label="ポッドキャスト",
        publish="manual",
        metrics="manual",
        format="text",
        metric_fields=(MetricField("views", "再生数"),),
        primary_metric="views",
    ),
}

# テーブルの CHECK 制約用。チャネルを足すときはマイグレーションで制約を張り直す。
CHANNEL_CHECK_VALUES = ", ".join(f"'{c.value}'" for c in ChannelCode)
