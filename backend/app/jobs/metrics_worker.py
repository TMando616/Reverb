"""指標・RSS のジョブのワーカー（metrics design.md §6-1）。

1周の流れ（変換ワーカーと同じ形・ADR-0017）：

1. 止まった item を回収し、時刻が来た1件を ``running`` にする（別セッション → commit）
2. 取得に要るものを読む（トークンの復号など。別セッション・読むだけ）
3. **DB の接続もロックも持たずに**外部 API を呼ぶ
4. 結果を書き、item を確定する（別セッション → commit）。失敗はリトライか確定失敗かを
   JobService が決める

種類ごとの処理は ``ItemHandler`` で差し込む（Qiita は §4、RSS は §5 で足す）。
commit の持ち主はここ。Service は flush まで。
"""

import logging
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs import loop, scheduler
from app.jobs.worker import SessionFactory
from app.modules.metrics.deps import build_job_service
from app.modules.metrics.models import JobKind
from app.modules.metrics.ports import JobFailed
from app.modules.metrics.service import ClaimedItem, JobService

logger = logging.getLogger("app.jobs.metrics_worker")

POLL_INTERVAL_SECONDS = 2.0

ServiceFactory = Callable[[AsyncSession], JobService]


class ItemHandler(Protocol):
    """1種類のジョブの処理。どの段階でも ``JobFailed`` を投げれば失敗として扱う。"""

    async def prepare(self, session: AsyncSession, item: ClaimedItem) -> Any:
        """DB から取得に要るものを読む（書かない）。"""
        ...

    async def fetch(self, prepared: Any) -> Any:
        """DB の外で外部 API を呼ぶ。"""
        ...

    async def store(self, session: AsyncSession, item: ClaimedItem, fetched: Any) -> None:
        """結果を書く。item の成功と同じトランザクションになる。"""
        ...


Handlers = Mapping[JobKind, ItemHandler]


def default_handlers() -> dict[JobKind, ItemHandler]:
    """本番の組み立て。Qiita（metrics 4.2）と RSS（metrics 5.4）をここに足す。"""
    return {}


async def run_once(
    sessions: SessionFactory,
    handlers: Handlers,
    build: ServiceFactory = build_job_service,
) -> bool:
    """1件処理したら True、時刻が来た item が無ければ False。"""
    async with sessions() as session:
        service = build(session)
        reaped = await service.reap_stuck()
        claimed = await service.claim()
        await session.commit()
    if reaped:
        logger.warning("reaped %d stuck metrics job items", reaped)
    if claimed is None:
        return False

    try:
        handler = handlers.get(claimed.kind)
        if handler is None:
            raise JobFailed("internal_error", f"no handler for {claimed.kind}", retryable=False)
        async with sessions() as session:
            prepared = await handler.prepare(session, claimed)
            # 読むだけなので書き戻さない（ロックも持ち越さない）
            await session.rollback()
        fetched = await handler.fetch(prepared)
        async with sessions() as session:
            try:
                await handler.store(session, claimed, fetched)
                await build(session).succeed(claimed.item_id)
                await session.commit()
            except BaseException:
                await session.rollback()
                raise
    except JobFailed as failure:
        await _record_failure(sessions, build, claimed, failure)
    except Exception:
        # 想定外でも running のまま残さない（回収まで10分待たせない）。リトライはする
        logger.exception("metrics job item %s crashed", claimed.item_id)
        await _record_failure(
            sessions, build, claimed, JobFailed("internal_error", "unexpected error")
        )
    return True


async def _record_failure(
    sessions: SessionFactory, build: ServiceFactory, item: ClaimedItem, failure: JobFailed
) -> None:
    try:
        async with sessions() as session:
            await build(session).fail(item.item_id, failure)
            await session.commit()
    except Exception:
        # 失敗の記録もできなければ、最後は回収に任せる
        logger.exception("could not record the failure of metrics job item %s", item.item_id)


async def run_forever(
    sessions: SessionFactory,
    handlers: Handlers,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """lifespan から起動し、終了時にキャンセルされる。60秒に1回 ``scheduler.tick`` を呼ぶ。"""
    last_tick: float | None = None

    async def iteration() -> bool:
        nonlocal last_tick
        now = clock()
        if last_tick is None or now - last_tick >= scheduler.TICK_INTERVAL_SECONDS:
            last_tick = now
            try:
                await scheduler.tick(sessions)
            except Exception:
                # 投入に失敗しても、入っている item の処理は続ける
                logger.exception("metrics scheduler tick failed")
        return await run_once(sessions, handlers)

    await loop.run_forever(iteration, interval=POLL_INTERVAL_SECONDS, name="metrics")
