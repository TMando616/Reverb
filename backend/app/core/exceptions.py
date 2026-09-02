"""Application exception hierarchy (design.md §6-3).

Services raise these; ``exception_handlers`` maps each to an HTTP status and the
``{"error": {"code", "message"}}`` envelope. Services never import FastAPI, so
they must not raise ``HTTPException``.
"""


class AppError(Exception):
    """Base class for domain errors. Subclasses set ``status`` and ``code``."""

    status: int = 500
    code: str = "internal_error"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.code
        super().__init__(self.message)


class AuthenticationError(AppError):
    """Missing / invalid / expired / revoked token, or failed login."""

    status = 401
    code = "authentication_error"

    def __init__(self, message: str = "authentication required") -> None:
        super().__init__(message)


class ForbiddenError(AppError):
    """Authenticated but lacks permission (includes demo write attempts)."""

    status = 403
    code = "forbidden"

    def __init__(self, message: str = "operation not permitted") -> None:
        super().__init__(message)


class NotFoundError(AppError):
    """Resource absent, hidden from a non-member, or an invalid invite token."""

    status = 404
    code = "not_found"

    def __init__(self, resource: str = "resource") -> None:
        super().__init__(f"{resource} not found")


class VersionConflictError(AppError):
    """``expected_version`` mismatch or ``StaleDataError`` (design.md §3-3)."""

    status = 409
    code = "version_conflict"

    def __init__(self, message: str = "resource was modified by another request") -> None:
        super().__init__(message)


class InvalidStateTransitionError(AppError):
    """A content status transition the table does not allow (design.md §8)."""

    status = 422
    code = "invalid_state_transition"

    def __init__(self, message: str = "invalid state transition") -> None:
        super().__init__(message)
