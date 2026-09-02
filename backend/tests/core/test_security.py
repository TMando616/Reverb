"""Unit tests for password hashing and token helpers (design.md §4-1 / §4-2)."""

from app.core.security import (
    DUMMY_PASSWORD_HASH,
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)


def test_hash_password_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password(hashed, "correct horse battery staple")
    assert not verify_password(hashed, "wrong password")


def test_verify_password_never_raises_on_garbage_hash() -> None:
    assert verify_password("not-a-real-argon2-hash", "whatever") is False


def test_dummy_hash_is_usable_for_timing_equalisation() -> None:
    # design.md §4-2: login verifies against this when the email is unknown.
    assert verify_password(DUMMY_PASSWORD_HASH, "anything") is False


def test_tokens_are_unique_and_hash_is_stable() -> None:
    a, b = generate_token(), generate_token()
    assert a != b
    assert hash_token(a) == hash_token(a)
    assert hash_token(a) != hash_token(b)
    assert len(hash_token(a)) == 64  # sha256 hex
