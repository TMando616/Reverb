"""``ClaudeConverter`` のテスト（publishing design.md §8-3・§15）。

**実際の API は呼ばない。** SDK のクライアントを差し替え、``stop_reason``・Schema 不一致・
各例外が ``error_code`` に写ることと、送るパラメータだけを確かめる。
"""

import json
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from app.channels.capabilities import ChannelCode
from app.llm.converter import FALLBACK_BETA, MAX_TOKENS, ClaudeConverter
from app.modules.publishing.ports import ConversionFailed, ConversionInput
from app.modules.publishing.profiles import DEFAULT_PROFILES

REQUEST = ConversionInput(
    channel_label="Qiita",
    format="markdown",
    max_length=None,
    title="ECS の話",
    body_md="ECS のタスク定義でハマった話",
    profile=DEFAULT_PROFILES[ChannelCode.QIITA],
    existing_tags=["AWS"],
)
GOOD = json.dumps({"title": "T", "body": "# B", "tags": ["AWS", "ECS"]})


def _message(text: str | None = GOOD, stop_reason: str = "end_turn") -> Any:
    content = [SimpleNamespace(type="thinking", thinking="")]
    if text is not None:
        content.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=content,
        usage=SimpleNamespace(input_tokens=120, output_tokens=340),
        _request_id="req_123",
    )


class _Stream:
    def __init__(self, outcome: Any) -> None:
        self._outcome = outcome

    async def __aenter__(self) -> "_Stream":
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get_final_message(self) -> Any:
        return self._outcome


class _FakeClient:
    def __init__(self, outcome: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        outer = self

        class _Messages:
            def stream(self, **kwargs: Any) -> _Stream:
                outer.calls.append(kwargs)
                return _Stream(outcome)

        self.beta = SimpleNamespace(messages=_Messages())


def _converter(outcome: Any) -> tuple[ClaudeConverter, _FakeClient]:
    client = _FakeClient(outcome)
    return ClaudeConverter(client, model="claude-opus-5-5", effort="medium"), client  # type: ignore[arg-type]


def _status_error(cls: type[anthropic.APIStatusError], status: int) -> anthropic.APIStatusError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, request=request, headers={"request-id": "req_err"})
    return cls("boom", response=response, body=None)


async def test_success_returns_the_parsed_output_and_usage() -> None:
    converter, client = _converter(_message())

    output = await converter.convert(REQUEST)

    assert (output.title, output.body, output.tags) == ("T", "# B", ["AWS", "ECS"])
    assert (output.request_id, output.input_tokens, output.output_tokens) == ("req_123", 120, 340)
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["max_tokens"] == MAX_TOKENS
    assert call["output_config"]["effort"] == "medium"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default"
    assert call["betas"] == [FALLBACK_BETA]
    assert "thinking" not in call
    assert "ECS のタスク定義でハマった話" in call["messages"][0]["content"]
    assert "ECS のタスク定義でハマった話" not in call["system"]


@pytest.mark.parametrize(
    ("message", "code"),
    [
        (_message(stop_reason="refusal", text=None), "refused"),
        (_message(stop_reason="max_tokens"), "truncated"),
        (_message(text="not json"), "invalid_output"),
        (_message(text=json.dumps({"title": "T"})), "invalid_output"),
        (_message(text=None), "invalid_output"),
    ],
    ids=["refusal", "max_tokens", "not-json", "schema-mismatch", "no-text"],
)
async def test_bad_responses_become_error_codes(message: Any, code: str) -> None:
    converter, _ = _converter(message)

    with pytest.raises(ConversionFailed) as excinfo:
        await converter.convert(REQUEST)

    assert excinfo.value.error_code == code
    assert excinfo.value.request_id == "req_123"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (_status_error(anthropic.RateLimitError, 429), "rate_limited"),
        (_status_error(anthropic.AuthenticationError, 401), "misconfigured"),
        (_status_error(anthropic.PermissionDeniedError, 403), "misconfigured"),
        (_status_error(anthropic.NotFoundError, 404), "misconfigured"),
        (_status_error(anthropic.BadRequestError, 400), "bad_request"),
        (_status_error(anthropic.InternalServerError, 500), "upstream_unavailable"),
        (_status_error(anthropic.APIStatusError, 529), "upstream_unavailable"),
    ],
    ids=["429", "401", "403", "404", "400", "500", "529"],
)
async def test_api_errors_become_error_codes(error: Exception, code: str) -> None:
    converter, _ = _converter(error)

    with pytest.raises(ConversionFailed) as excinfo:
        await converter.convert(REQUEST)

    assert excinfo.value.error_code == code
    assert excinfo.value.request_id == "req_err"


@pytest.mark.parametrize(
    "error",
    [
        anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")),
        anthropic.APITimeoutError(request=httpx2.Request("POST", "https://x")),
    ],
    ids=["connection", "timeout"],
)
async def test_network_errors_are_upstream_unavailable(error: Exception) -> None:
    converter, _ = _converter(error)

    with pytest.raises(ConversionFailed) as excinfo:
        await converter.convert(REQUEST)

    assert excinfo.value.error_code == "upstream_unavailable"


async def test_missing_credentials_are_misconfigured() -> None:
    error = TypeError("Could not resolve authentication method. Expected one of api_key, ...")
    converter, _ = _converter(error)

    with pytest.raises(ConversionFailed) as excinfo:
        await converter.convert(REQUEST)

    assert excinfo.value.error_code == "misconfigured"


async def test_other_type_errors_are_not_swallowed() -> None:
    converter, _ = _converter(TypeError("a bug"))

    with pytest.raises(TypeError, match="a bug"):
        await converter.convert(REQUEST)
