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


@dataclass(frozen=True)
class Capabilities:
    label: str
    publish: PublishMode
    metrics: MetricsMode
    format: Format
    max_length: int | None = None


CAPABILITIES: dict[ChannelCode, Capabilities] = {
    ChannelCode.QIITA: Capabilities(
        label="Qiita", publish="auto", metrics="auto", format="markdown"
    ),
    # 以下は M3 で使う。文字数の数え方（全角を2と数える等）は M3 着手時に確認する。
    ChannelCode.X: Capabilities(
        label="X", publish="intent", metrics="manual", format="text", max_length=280
    ),
    ChannelCode.NOTE: Capabilities(
        label="note", publish="manual", metrics="manual", format="markdown"
    ),
    ChannelCode.PODCAST: Capabilities(
        label="ポッドキャスト", publish="manual", metrics="manual", format="text"
    ),
}

# テーブルの CHECK 制約用。チャネルを足すときはマイグレーションで制約を張り直す。
CHANNEL_CHECK_VALUES = ", ".join(f"'{c.value}'" for c in ChannelCode)
