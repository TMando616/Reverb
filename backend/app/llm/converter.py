"""Claude API による変換（publishing design.md §8）。

`/claude-api` スキルを読んで決めた形（2026-10-18・SDK 1.15）：
- ``AsyncAnthropic`` の ``beta.messages.stream`` ＋ ``get_final_message()``。
  記事1本分の出力は長いのでストリーミングで受ける（HTTP タイムアウト回避）。途中経過は使わない
- ``thinking`` は送らない（Opus 5.5 は常に adaptive。``disabled`` は 400）。深さは effort で決める
- 出力は structured outputs（``output_config.format``）で ``{title, body, tags}`` に固定する
- ``fallbacks: "default"``（beta ``server-side-fallback-2026-07-01``）で、安全分類器の拒否は
  サーバー側で別モデルに回す。それでも ``refusal`` なら失敗にする
- 再試行は SDK の既定（2回）だけ。アプリ側で重ねない（requirements §6）
- 本文・プロンプトはログにも例外にも出さない
"""

import asyncio
import json
import logging
from typing import Literal

import anthropic
from anthropic import AsyncAnthropic
from pydantic import BaseModel, ValidationError

from app.llm.prompts import OUTPUT_SCHEMA, build_system, build_user
from app.modules.publishing.ports import ConversionFailed, ConversionInput, ConversionOutput

logger = logging.getLogger("app.llm")

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 64_000
TIMEOUT_SECONDS = 600.0
# 変換1回の全体の締め切り。SDK の timeout はストリーミングでは「チャンクの間隔」に効き、
# 再試行（既定2回）も重なるので、それだけでは全体の長さが決まらない。ワーカーの回収
# （service.STUCK_AFTER＝30分）より短くして、生きている実行が回収されないようにする。
CONVERSION_DEADLINE_SECONDS = 20 * 60

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class _Output(BaseModel):
    title: str
    body: str
    tags: list[str]


class ClaudeConverter:
    def __init__(self, client: AsyncAnthropic, *, model: str, effort: Effort) -> None:
        self._client = client
        self._model = model
        self._effort = effort

    async def convert(self, request: ConversionInput) -> ConversionOutput:
        try:
            async with (
                asyncio.timeout(CONVERSION_DEADLINE_SECONDS),
                self._client.beta.messages.stream(
                    model=self._model,
                    max_tokens=MAX_TOKENS,
                    system=build_system(request),
                    messages=[{"role": "user", "content": build_user(request)}],
                    output_config={
                        "effort": self._effort,
                        "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
                    },
                    betas=[FALLBACK_BETA],
                    fallbacks="default",
                ) as stream,
            ):
                message = await stream.get_final_message()
        # 具体的な例外から順に捕まえる（RateLimitError も APIStatusError の子）。
        except anthropic.RateLimitError as exc:
            raise ConversionFailed("rate_limited", "rate limited", exc.request_id) from None
        except (
            anthropic.AuthenticationError,
            anthropic.PermissionDeniedError,
            anthropic.NotFoundError,
        ) as exc:
            # キーの値は例外に出さない。NotFound はモデル名の設定ミス。
            logger.error("claude api misconfigured: status=%s", exc.status_code)
            raise ConversionFailed(
                "misconfigured", "api is misconfigured", exc.request_id
            ) from None
        except anthropic.BadRequestError as exc:
            raise ConversionFailed("bad_request", "request was rejected", exc.request_id) from None
        except anthropic.APIStatusError as exc:
            code = "upstream_unavailable" if exc.status_code >= 500 else "bad_request"
            raise ConversionFailed(
                code, f"api returned {exc.status_code}", exc.request_id
            ) from None
        except TimeoutError:
            raise ConversionFailed("upstream_unavailable", "the conversion took too long") from None
        except anthropic.APIConnectionError:
            # APITimeoutError もここ（APIConnectionError の子）。
            raise ConversionFailed("upstream_unavailable", "could not reach the api") from None
        except TypeError as exc:
            # API キーが無いと、SDK は送信前に API エラーではなく TypeError を投げる。
            if "authentication method" not in str(exc):
                raise
            logger.error("claude api misconfigured: no credentials")
            raise ConversionFailed("misconfigured", "api credentials are not set") from None

        request_id = getattr(message, "_request_id", None)
        if message.stop_reason == "refusal":
            raise ConversionFailed("refused", "the model declined the conversion", request_id)
        if message.stop_reason == "max_tokens":
            raise ConversionFailed("truncated", "the output was cut off", request_id)
        text = next((block.text for block in message.content if block.type == "text"), None)
        if text is None:
            raise ConversionFailed("invalid_output", "no text in the response", request_id)
        try:
            output = _Output.model_validate(json.loads(text))
        except (ValueError, ValidationError):
            raise ConversionFailed(
                "invalid_output", "the output did not match the schema", request_id
            ) from None
        return ConversionOutput(
            title=output.title,
            body=output.body,
            tags=output.tags,
            request_id=request_id,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )


def build_client() -> AsyncAnthropic:
    """API キーは SDK に環境変数（ANTHROPIC_API_KEY）から解決させる（design.md §8-1）。"""
    return AsyncAnthropic(timeout=TIMEOUT_SECONDS)
