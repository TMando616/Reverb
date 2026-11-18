"""ポーリングのループ（ADR-0013「共通にするのは拾い方だけ」・metrics design.md §2）。

変換と指標のワーカーで共通にするのはここだけ。拾う SQL はテーブルごとに各モジュールの
Repository に置く。1周の失敗でループを止めず、キャンセル（lifespan の終了）だけで抜ける。
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger("app.jobs.loop")


async def run_forever(
    run_once: Callable[[], Awaitable[bool]], *, interval: float, name: str
) -> None:
    """``run_once`` が仕事をした（True）なら間を置かずに次を拾い、無ければ ``interval`` 秒待つ。"""
    logger.info("%s worker started", name)
    while True:
        try:
            worked = await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("%s worker iteration failed", name)
            worked = False
        if not worked:
            await asyncio.sleep(interval)
