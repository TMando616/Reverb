"""パスワードハッシュ（Argon2id）とオペークなセッショントークンのヘルパー。

- パスワード：``argon2-cffi`` による Argon2id（design.md §4-2）。
- セッショントークン：オペークなランダム文字列。サーバー側で保持するのは
  sha256 だけ（design.md §4-1）。生のトークンはクライアントに1回だけ返す。
"""

import hashlib
import secrets

import anyio
import anyio.to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# email が未登録のときに検証する固定の Argon2id ハッシュ。これにより、
# ログインはどちらの分岐でも同じ CPU コストを払い、タイミングでアドレスの
# 登録有無が漏れない（design.md §4-2）。import 時に一度だけ計算する。
DUMMY_PASSWORD_HASH: str = _hasher.hash("reverb-nonexistent-account")


def hash_password(password: str) -> str:
    """``password`` の Argon2id ハッシュを返す（同期・CPU バウンド）。"""
    return _hasher.hash(password)


def verify_password(hashed: str, password: str) -> bool:
    """``password`` が ``hashed`` と一致するかを返す（同期）。例外は投げない。"""
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# Argon2id は1回あたり数十 ms・64 MiB を使う。イベントループ上で直接回すと、
# ログインが数件重なるだけで他のリクエスト（/health や読み取り）まで待たされる。
# async のコードからはこの2つを使い、ワーカースレッドへ逃がす。
#
# ただし anyio の既定スレッドプール（40）に素で流すと、未認証で叩ける
# POST /auth/login が 40 並列 × 64 MiB ≒ 2.5 GiB を確保しうる。専用の
# CapacityLimiter で同時実行数を絞り、FastAPI が同期処理に使う既定プールとも
# 取り合わないようにする。
_PASSWORD_HASH_CONCURRENCY = 4
_password_limiter = anyio.CapacityLimiter(_PASSWORD_HASH_CONCURRENCY)


async def hash_password_async(password: str) -> str:
    return await anyio.to_thread.run_sync(hash_password, password, limiter=_password_limiter)


async def verify_password_async(hashed: str, password: str) -> bool:
    return await anyio.to_thread.run_sync(
        verify_password, hashed, password, limiter=_password_limiter
    )


def generate_token() -> str:
    """新しいオペークなセッショントークンを返す（URL セーフ）。"""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """``sessions.token_hash`` に保存する sha256 の16進ダイジェストを返す（design.md §4-1）。"""
    return hashlib.sha256(token.encode()).hexdigest()
