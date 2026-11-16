"""日付の境界（JST）。

指標の「その日」は JST で数える（metrics design.md §3-2）。サーバーの TZ に依存させないため、
UTC の時刻からここで変換する。
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def jst_date(moment: datetime) -> date:
    """aware な時刻を JST の日付にする。naive は受け付けない（どの TZ か分からないため）。"""
    if moment.tzinfo is None:
        raise ValueError("naive datetime is not allowed")
    return moment.astimezone(JST).date()
