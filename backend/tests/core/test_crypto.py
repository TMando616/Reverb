"""トークン暗号化のテスト（publishing design.md §10-1・§15）。"""

import pytest
from app.core.crypto import TokenCipher, TokenUnavailableError
from cryptography.fernet import Fernet

TOKEN = "qiita-secret-token-0123456789"


def _key() -> str:
    return Fernet.generate_key().decode()


def test_round_trip_and_the_ciphertext_does_not_contain_the_token() -> None:
    cipher = TokenCipher([_key()])

    encrypted = cipher.encrypt(TOKEN)

    assert TOKEN.encode() not in encrypted
    decrypted = cipher.decrypt(encrypted)
    assert decrypted.plaintext == TOKEN
    assert decrypted.stale is False


def test_old_key_still_decrypts_after_rotation_and_is_marked_stale() -> None:
    old, new = _key(), _key()
    encrypted = TokenCipher([old]).encrypt(TOKEN)

    decrypted = TokenCipher([new, old]).decrypt(encrypted)

    assert decrypted.plaintext == TOKEN
    assert decrypted.stale is True


def test_tampered_ciphertext_is_rejected_without_leaking_values() -> None:
    cipher = TokenCipher([_key()])
    encrypted = bytearray(cipher.encrypt(TOKEN))
    encrypted[-5] ^= 0x01

    with pytest.raises(TokenUnavailableError) as excinfo:
        cipher.decrypt(bytes(encrypted))

    assert TOKEN not in str(excinfo.value)
    assert bytes(encrypted).decode() not in str(excinfo.value)


def test_a_removed_key_makes_the_token_unavailable() -> None:
    encrypted = TokenCipher([_key()]).encrypt(TOKEN)

    with pytest.raises(TokenUnavailableError):
        TokenCipher([_key()]).decrypt(encrypted)


def test_no_keys_means_unavailable() -> None:
    with pytest.raises(TokenUnavailableError):
        TokenCipher([]).encrypt(TOKEN)


def test_an_invalid_key_fails_without_echoing_it() -> None:
    with pytest.raises(ValueError) as excinfo:
        TokenCipher(["not-a-fernet-key"])

    assert "not-a-fernet-key" not in str(excinfo.value)
