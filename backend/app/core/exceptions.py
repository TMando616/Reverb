"""アプリケーションの例外階層（design.md §6-3）。

Service はこれらを投げる。``exception_handlers`` が各例外を HTTP ステータスと
``{"error": {"code", "message"}}`` の封筒にマッピングする。Service は FastAPI を
import しないので、``HTTPException`` を投げてはいけない。
"""


class AppError(Exception):
    """ドメイン例外の基底クラス。サブクラスが ``status`` と ``code`` を設定する。"""

    status: int = 500
    code: str = "internal_error"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.code
        super().__init__(self.message)


class AuthenticationError(AppError):
    """トークンが無い・不正・期限切れ・失効、またはログイン失敗。"""

    status = 401
    code = "authentication_error"

    def __init__(self, message: str = "authentication required") -> None:
        super().__init__(message)


class ForbiddenError(AppError):
    """認証は通ったが権限が無い（demo の書き込み試行も含む）。"""

    status = 403
    code = "forbidden"

    def __init__(self, message: str = "operation not permitted") -> None:
        super().__init__(message)


class NotFoundError(AppError):
    """リソースが存在しない、非メンバーから隠されている、または無効な招待トークン。"""

    status = 404
    code = "not_found"

    def __init__(self, resource: str = "resource") -> None:
        super().__init__(f"{resource} not found")


class VersionConflictError(AppError):
    """``expected_version`` の不一致、または ``StaleDataError``（design.md §3-3）。"""

    status = 409
    code = "version_conflict"

    def __init__(self, message: str = "resource was modified by another request") -> None:
        super().__init__(message)


class InvalidStateTransitionError(AppError):
    """遷移表で許可されていないコンテンツの状態遷移（design.md §8）。"""

    status = 422
    code = "invalid_state_transition"

    def __init__(self, message: str = "invalid state transition") -> None:
        super().__init__(message)


class TagNameConflictError(AppError):
    """同じ企画に、正規化後に同じ名前のタグがある（content-pipeline design.md §6-4）。

    409 が ``version_conflict`` と2種類になるので、クライアントは ``code`` で区別する。
    """

    status = 409
    code = "tag_name_conflict"

    def __init__(self, message: str = "a tag with the same name already exists") -> None:
        super().__init__(message)


class InvalidTagError(AppError):
    """付けようとしたタグがこの企画に無い、または上限を超える（content-pipeline design.md §6-4）。

    他企画のタグと存在しないタグを区別しない（他企画のタグの存在を漏らさない）。
    """

    status = 422
    code = "invalid_tag"

    def __init__(self, message: str = "invalid tag") -> None:
        super().__init__(message)


# --- publishing（publishing design.md §12）。409 の意味が増えるので画面は code で分岐する ---


class ConversionInProgressError(AppError):
    """同じコンテンツ×チャネルで変換が待機中・実行中（部分 UNIQUE・C3）。"""

    status = 409
    code = "conversion_in_progress"

    def __init__(self, message: str = "a conversion is already in progress") -> None:
        super().__init__(message)


class UnsupportedChannelError(AppError):
    """このチャネルでは、その操作がまだできない（M1 で変換できるのは Qiita だけ等）。"""

    status = 422
    code = "unsupported_channel"

    def __init__(self, message: str = "this channel does not support the operation yet") -> None:
        super().__init__(message)


class PublicationExistsError(AppError):
    """取り消されていない公開物がすでにある。新規投稿ではなく更新を使う。"""

    status = 409
    code = "publication_exists"

    def __init__(self, message: str = "already published to this channel") -> None:
        super().__init__(message)


class QiitaTokenMissingError(AppError):
    status = 409
    code = "qiita_token_missing"

    def __init__(self, message: str = "qiita access token is not registered") -> None:
        super().__init__(message)


class QiitaTokenInvalidError(AppError):
    """登録済みのトークンが無効・権限不足（write_qiita）・復号できない。再登録へ誘導する。"""

    status = 409
    code = "qiita_token_invalid"

    def __init__(self, message: str = "qiita access token is invalid or lacks write_qiita") -> None:
        super().__init__(message)


class QiitaItemMissingError(AppError):
    """更新しようとした記事が Qiita 側で消えている。公開取消を案内する。"""

    status = 409
    code = "qiita_item_missing"

    def __init__(self, message: str = "the item no longer exists on qiita") -> None:
        super().__init__(message)


class InvalidQiitaTokenError(AppError):
    """登録しようとしたトークンを Qiita が受け付けなかった。"""

    status = 422
    code = "invalid_qiita_token"

    def __init__(self, message: str = "qiita rejected the access token") -> None:
        super().__init__(message)


class InvalidDraftError(AppError):
    """原稿がチャネルの制約（Qiita のタグ数・タイトル等）を満たさない。"""

    status = 422
    code = "invalid_draft"

    def __init__(self, message: str = "the draft does not satisfy the channel's rules") -> None:
        super().__init__(message)


class QiitaRejectedPublishError(AppError):
    """Qiita が投稿・更新を拒否した。message は Qiita の文言（トークンは含まない）。"""

    status = 422
    code = "qiita_rejected"

    def __init__(self, message: str = "qiita rejected the item") -> None:
        super().__init__(message)


class QiitaUnavailableAppError(AppError):
    status = 502
    code = "qiita_unavailable"

    def __init__(self, message: str = "qiita is unavailable") -> None:
        super().__init__(message)


class QiitaRateLimitedAppError(AppError):
    status = 503
    code = "qiita_rate_limited"

    def __init__(self, message: str = "qiita rate limit exceeded") -> None:
        super().__init__(message)
