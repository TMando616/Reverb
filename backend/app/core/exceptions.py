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
