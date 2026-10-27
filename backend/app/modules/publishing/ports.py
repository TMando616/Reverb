"""publishing の Service から見た外部の境界（ポート）（publishing design.md §1-2）。

Service はここにある Protocol とデータの型だけを知る。具体実装（Qiita API・Claude API）は
``app/channels`` / ``app/llm`` に置き、``deps.py`` で差し込む。テストは fake を差し込む。
実装側もここを import して型と例外をそろえる（依存の向きは「実装 → ポート」）。
"""

from dataclasses import dataclass
from typing import Protocol

# --- Qiita（design.md §10） ---


@dataclass(frozen=True, slots=True)
class QiitaItemInput:
    title: str
    body: str
    tags: list[str]
    private: bool


@dataclass(frozen=True, slots=True)
class QiitaItemRef:
    id: str
    url: str


class QiitaError(Exception):
    """Qiita API の失敗。メッセージにトークンを含めない。"""


class QiitaAuthError(QiitaError):
    """401 / 403。トークンが無効か、``write_qiita`` スコープが無い。"""


class QiitaRejectedError(QiitaError):
    """400 / 422。Qiita が内容を受け付けなかった。``message`` は Qiita の文言。"""


class QiitaNotFoundError(QiitaError):
    """404。更新しようとした記事が Qiita 側で消えている。"""


class QiitaRateLimitedError(QiitaError):
    """429。"""


class QiitaUnavailableError(QiitaError):
    """5xx・タイムアウト・接続エラー。"""


class QiitaGateway(Protocol):
    async def authenticated_user(self, token: str) -> str:
        """トークンの持ち主の Qiita ユーザー名を返す。"""
        ...

    async def create_item(self, token: str, item: QiitaItemInput) -> QiitaItemRef: ...

    async def update_item(self, token: str, item_id: str, item: QiitaItemInput) -> QiitaItemRef: ...


# --- トークンの暗号化（design.md §10-1。実体は core.crypto.TokenCipher） ---


class DecryptedToken(Protocol):
    @property
    def plaintext(self) -> str: ...

    @property
    def stale(self) -> bool: ...


class TokenCipherPort(Protocol):
    def encrypt(self, plaintext: str) -> bytes: ...

    def decrypt(self, ciphertext: bytes) -> DecryptedToken: ...
