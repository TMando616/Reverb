"""metrics の Service から見た外部の境界（ポート）（metrics design.md §2）。

Service はここにある Protocol とデータの型だけを知る。公開物は publishing の持ち物なので、
読むのも ``PublicationGateway`` 越しにする（実体は ``deps.py`` で差し込む）。
"""

from collections.abc import Mapping
from typing import Protocol

from app.channels.capabilities import MetricColumn
from app.modules.publishing.models import Publication

# 指標の列と値。キーに無い列・None はその日に取れなかった（NULL）として扱う。
MetricValues = Mapping[MetricColumn, int | None]


class PublicationGateway(Protocol):
    async def get_in_project(self, publication_id: int, project_id: int) -> Publication | None:
        """取り消した公開物も返す（取消後も推移は読めるようにする・S1）。"""
        ...
