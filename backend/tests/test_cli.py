"""bootstrap CLI のユニットテスト（design.md §9-0）。

ここでカバーするのはパスワード解決だけ：repository に一切触れない、実質的な
ロジックを持つ唯一の分岐であり、パスワードを argv やシェル履歴から遠ざけている
部分。コマンド本体は、すでにテスト済みの repository と ``InvitationService`` の
薄いラッパーに過ぎない。
"""

import asyncio

import pytest
from app.cli import CommandError, _create_user, _resolve_password


def test_generates_and_reports_a_generated_password(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    password, was_generated = _resolve_password(generate=True)

    assert was_generated is True
    assert password


def test_prompts_twice_and_returns_the_typed_password(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda prompt: "s3cret-pass")

    password, was_generated = _resolve_password(generate=False)

    assert (password, was_generated) == ("s3cret-pass", False)


def test_rejects_mismatched_confirmation(monkeypatch):
    answers = iter(["first-pass", "second-pass"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda prompt: next(answers))

    with pytest.raises(CommandError, match="did not match"):
        _resolve_password(generate=False)


def test_rejects_an_empty_password(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda prompt: "")

    with pytest.raises(CommandError, match="must not be empty"):
        _resolve_password(generate=False)


def test_refuses_to_prompt_without_a_tty(monkeypatch):
    # 非対話実行（CI・``docker compose exec -T``）では誰も答えられないプロンプトで
    # 止めず、生成するように伝える必要がある。
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    with pytest.raises(CommandError, match="--generate-password"):
        _resolve_password(generate=False)


def test_rejects_an_overlong_display_name() -> None:
    # varchar(100) 超過を DataError のトレースバックではなく CommandError にする。
    with pytest.raises(CommandError, match="display-name"):
        asyncio.run(
            _create_user(
                None,  # type: ignore[arg-type]  # 長さ検証は session に触れる前に走る
                email="x@example.com",
                display_name="あ" * 101,
                is_demo=False,
                password="pw",
                was_generated=False,
            )
        )


def test_rejects_an_overlong_email() -> None:
    with pytest.raises(CommandError, match="email"):
        asyncio.run(
            _create_user(
                None,  # type: ignore[arg-type]
                email="a" * 311 + "@example.com",
                display_name="名前",
                is_demo=False,
                password="pw",
                was_generated=False,
            )
        )
