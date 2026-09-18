"""パスワードハッシュ（Argon2id）とオペークなセッショントークンのヘルパー。

- パスワード：``argon2-cffi`` による Argon2id（design.md §4-2）。
- セッショントークン：オペークなランダム文字列。サーバー側で保持するのは
  sha256 だけ（design.md §4-1）。生のトークンはクライアントに1回だけ返す。
"""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# email が未登録のときに検証する固定の Argon2id ハッシュ。これにより、
# ログインはどちらの分岐でも同じ CPU コストを払い、タイミングでアドレスの
# 登録有無が漏れない（design.md §4-2）。import 時に一度だけ計算する。
DUMMY_PASSWORD_HASH: str = _hasher.hash("reverb-nonexistent-account")


def hash_password(password: str) -> str:
    """``password`` の Argon2id ハッシュを返す。"""
    return _hasher.hash(password)


def verify_password(hashed: str, password: str) -> bool:
    """``password`` が ``hashed`` と一致するかを返す。例外は投げない。"""
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def generate_token() -> str:
    """新しいオペークなセッショントークンを返す（URL セーフ）。"""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """``sessions.token_hash`` に保存する sha256 の16進ダイジェストを返す（design.md §4-1）。"""
    return hashlib.sha256(token.encode()).hexdigest()
