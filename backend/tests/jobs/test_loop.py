"""ポーリングのループのテスト（metrics design.md §2）。"""

import asyncio

import pytest
from app.jobs import loop


async def test_loop_survives_a_failed_iteration_and_sleeps_only_when_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results: list[object] = [True, RuntimeError("boom"), False, True]
    calls: list[str] = []
    sleeps: list[float] = []

    async def run_once() -> bool:
        calls.append("run")
        if not results:
            raise asyncio.CancelledError
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        assert isinstance(result, bool)
        return result

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    # loop.py が見る asyncio.sleep を差し替える（asyncio は loop.py と同じモジュール）
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await loop.run_forever(run_once, interval=2.0, name="test")

    # True → すぐ次へ / 例外 → 待つ / False → 待つ / True → すぐ次へ / キャンセルで抜ける
    assert len(calls) == 5
    assert sleeps == [2.0, 2.0]
