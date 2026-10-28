"""変換ジョブのワーカー（ADR-0017・publishing design.md §7-2）。

M1 はジョブ基盤を持たず、``conversion_jobs`` の行をキューにして同じプロセスの asyncio
タスクが拾う。1周の流れ：

1. 止まった行を回収し、待機中を1件 ``running`` にする（別セッション → commit）
2. **DB の接続もロックも持たずに** Claude を呼ぶ（数十秒〜数分かかる）
3. 結果を書き、原稿へ反映する（別セッション → commit）

commit の持ち主はここ（cli.py と同じく、Service の外にある commit）。Service は flush まで。
M2 でジョブ基盤に載せ替えるときは、このファイルだけを書き直す。
"""

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import VersionConflictError
from app.modules.publishing.deps import build_conversion_service
from app.modules.publishing.ports import ConversionFailed, ConversionOutput, Converter
from app.modules.publishing.service import ConversionService

logger = logging.getLogger("app.jobs.worker")

POLL_INTERVAL_SECONDS = 2.0

ServiceFactory = Callable[[AsyncSession], ConversionService]
# async_sessionmaker を想定。テストは外側トランザクションに乗るセッションを返す工場を渡す。
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


async def run_once(
    sessions: SessionFactory,
    converter: Converter,
    build: ServiceFactory = build_conversion_service,
) -> bool:
    """1件処理したら True、待機中が無ければ False。"""
    async with sessions() as session:
        service = build(session)
        await service.reap_stuck()
        claimed = await service.claim()
        await session.commit()
    if claimed is None:
        return False

    result: ConversionOutput | ConversionFailed
    try:
        result = await converter.convert(claimed.input)
    except ConversionFailed as failure:
        result = failure
    except Exception:
        # 想定外でもジョブを running のまま残さない（回収まで15分待たせない）。
        logger.exception("conversion job %s crashed", claimed.job_id)
        result = ConversionFailed("internal_error", "unexpected error during conversion")

    # 原稿の保存と同時に反映しようとすると楽観ロックで負ける。読み直してもう1回だけ試す
    # （2回目は「手で直した」を見て保留にする）。
    for attempt in range(2):
        async with sessions() as session:
            service = build(session)
            try:
                if isinstance(result, ConversionFailed):
                    await service.fail(claimed.job_id, result)
                else:
                    await service.complete(claimed.job_id, result)
                await session.commit()
                break
            except VersionConflictError:
                await session.rollback()
                if attempt == 1:
                    raise
    return True


async def run_forever(sessions: SessionFactory, converter: Converter) -> None:
    """lifespan から起動し、終了時にキャンセルされる。1周の失敗でループを止めない。"""
    logger.info("conversion worker started")
    while True:
        try:
            worked = await run_once(sessions, converter)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("conversion worker iteration failed")
            worked = False
        if not worked:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
