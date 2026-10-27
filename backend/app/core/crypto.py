"""外部サービスのトークンの暗号化（publishing design.md §10-1）。

Fernet（AES-128-CBC ＋ HMAC-SHA256 の認証付き暗号）を ``MultiFernet`` で束ねる。
先頭の鍵で暗号化し、全部の鍵で復号を試すので、鍵を差し替えても古い暗号文が読める。
自前で暗号を組まない。改ざんされた暗号文は復号で弾ける。

例外・ログにトークンも暗号文も含めない（C5）。
"""

from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class TokenUnavailableError(Exception):
    """復号できない（鍵が無い・違う・暗号文が壊れている）。メッセージに値を含めない。"""


@dataclass(frozen=True, slots=True)
class Decrypted:
    plaintext: str
    # 先頭以外の鍵で暗号化されていた。呼び出し側が暗号化し直して保存する。
    stale: bool


class TokenCipher:
    def __init__(self, keys: list[str]) -> None:
        # 鍵の形が不正なら起動時（deps の組み立て時）に落ちる。値は例外に出さない。
        try:
            self._fernets = [Fernet(k.encode()) for k in keys]
        except ValueError:
            raise ValueError("TOKEN_ENCRYPTION_KEYS contains an invalid Fernet key") from None

    def encrypt(self, plaintext: str) -> bytes:
        if not self._fernets:
            raise TokenUnavailableError("token encryption is not configured")
        return self._fernets[0].encrypt(plaintext.encode())

    def decrypt(self, ciphertext: bytes) -> Decrypted:
        if not self._fernets:
            raise TokenUnavailableError("token encryption is not configured")
        try:
            return Decrypted(self._fernets[0].decrypt(ciphertext).decode(), stale=False)
        except InvalidToken:
            pass
        try:
            plaintext = MultiFernet(self._fernets).decrypt(ciphertext).decode()
        except InvalidToken:
            raise TokenUnavailableError("stored token cannot be decrypted") from None
        return Decrypted(plaintext, stale=True)
