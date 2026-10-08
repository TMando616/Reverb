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
