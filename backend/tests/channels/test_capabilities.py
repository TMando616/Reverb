"""capabilities の指標の定義（metrics design.md §4）。"""

import pytest
from app.channels.capabilities import CAPABILITIES, METRIC_COLUMNS, ChannelCode


@pytest.mark.parametrize("channel", list(ChannelCode))
def test_every_channel_defines_metrics(channel: ChannelCode) -> None:
    caps = CAPABILITIES[channel]
    columns = [f.column for f in caps.metric_fields]
    assert columns, "指標が1つも無いと分析の対象にできない"
    assert len(columns) == len(set(columns)), "同じ列を2回定義しない"
    assert set(columns) <= set(METRIC_COLUMNS)
    # 代表指標はそのチャネルで意味のある列でなければならない（分析が NULL だけを比べてしまう）
    assert caps.primary_metric in caps.metric_columns()


def test_only_qiita_collects_automatically() -> None:
    # M2 で自動取得するのは Qiita だけ。ほかは手入力（requirements S2 / S7）
    auto = {c for c, caps in CAPABILITIES.items() if caps.metrics == "auto"}
    assert auto == {ChannelCode.QIITA}
