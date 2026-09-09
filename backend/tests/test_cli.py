"""Unit tests for the bootstrap CLI (design.md §9-0).

Only the password resolution is covered here: it is the one branch with real
logic that never reaches a repository, and it is what keeps the password out of
argv and the shell history. The commands themselves are thin wrappers over
already-tested repositories and ``InvitationService``.
"""

import pytest
from app.cli import CommandError, _resolve_password


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
    # Non-interactive runs (CI, `docker compose exec -T`) must be told to
    # generate rather than block on a prompt nobody can answer.
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    with pytest.raises(CommandError, match="--generate-password"):
        _resolve_password(generate=False)
