"""指標の定期投入（metrics design.md §6-3）。

metrics_worker のループから60秒に1回呼ぶ。別のタスク・別のプロセスにしない。
投入が1日1回になるのは DB の部分 UNIQUE で守るので、何度呼んでも、プロセスが
複数あってもよい。commit の持ち主はここ（Service は flush まで）。
"""

import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.worker import SessionFactory
from app.modules.metrics.deps import build_job_service
from app.modules.metrics.service import JobService

logger = logging.getLogger("app.jobs.scheduler")

TICK_INTERVAL_SECONDS = 60.0


async def tick(
    sessions: SessionFactory,
    build: Callable[[AsyncSession], JobService] = build_job_service,
) -> int:
    """今日の分が無い企画に定期実行を入れる。入れた run の数を返す。"""
    async with sessions() as session:
        inserted = await build(session).schedule_daily()
        await session.commit()
    if inserted:
        logger.info("scheduled %d metrics job runs", inserted)
    return inserted
