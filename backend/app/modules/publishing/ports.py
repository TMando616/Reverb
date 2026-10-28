"""publishing の Service から見た外部の境界（ポート）（publishing design.md §1-2）。

Service はここにある Protocol とデータの型だけを知る。具体実装（Qiita API・Claude API）は
``app/channels`` / ``app/llm`` に置き、``deps.py`` で差し込む。テストは fake を差し込む。
実装側もここを import して型と例外をそろえる（依存の向きは「実装 → ポート」）。
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from app.core.authorization import Actor
from app.modules.contents.models import Content

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


# --- 変換（design.md §7・§8。実体は llm.converter.ClaudeConverter） ---


@dataclass(frozen=True, slots=True)
class ProfileSnapshot:
    """変換プロファイルの中身。ジョブの ``profile_snapshot`` にそのまま写す（C2）。"""

    structure: str
    tone: str
    first_person: str
    banned_phrases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProfileSnapshot":
        return cls(
            structure=str(data["structure"]),
            tone=str(data["tone"]),
            first_person=str(data["first_person"]),
            banned_phrases=[str(p) for p in data.get("banned_phrases", [])],
        )


@dataclass(frozen=True, slots=True)
class ConversionInput:
    channel_label: str
    format: str  # "markdown" / "text"（capabilities.format）
    max_length: int | None
    title: str
    body_md: str
    profile: ProfileSnapshot
    # 企画の既存タグ名。タグ候補を既存に寄せるため（design.md §10-4）。
    existing_tags: list[str]


@dataclass(frozen=True, slots=True)
class ConversionOutput:
    title: str
    body: str
    tags: list[str]
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class ConversionFailed(Exception):
    """変換の失敗。``error_code`` は design.md §8-3 の表の値。メッセージに本文を含めない。"""

    def __init__(self, error_code: str, message: str, request_id: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.request_id = request_id


class Converter(Protocol):
    async def convert(self, request: ConversionInput) -> ConversionOutput: ...


class JobDispatcher(Protocol):
    """ジョブを実行側へ渡す。M1 は何もしない（ワーカーが DB の行を見つける・ADR-0017）。
    M2 でジョブ基盤に載せ替えるときは、ここをキューに積む実装に替える。
    """

    async def dispatch(self, job_id: int) -> None: ...


class NoopDispatcher:
    async def dispatch(self, job_id: int) -> None:
        return None


# --- コンテンツ（実体は contents.service.ContentService・design.md §2・§4） ---


class ContentGateway(Protocol):
    """publishing からコンテンツへの入口。状態遷移と遷移ログは contents の持ち物のまま。"""

    async def get(self, actor: Actor, project_id: int, content_id: int) -> Content: ...

    async def lock_for_publish(self, actor: Actor, project_id: int, content_id: int) -> Content: ...

    def ensure_publishable(self, content: Content) -> None: ...

    async def mark_published(self, actor: Actor, content: Content) -> None: ...

    async def mark_unpublished(self, actor: Actor, content: Content) -> None: ...

    async def latest_revision_no(self, content: Content) -> int: ...
