"""Application exception base and kinds (design.md §6-3).

Services raise these; ``exception_handlers`` maps them to HTTP status codes.
Services never import FastAPI, so they must not raise ``HTTPException``.
"""


class AppError(Exception):
    """Base class for all domain-level errors."""


class NotFoundError(AppError):
    """A referenced resource does not exist (or must not be revealed)."""


class PermissionDeniedError(AppError):
    """The actor is not allowed to perform this operation."""


class ConflictError(AppError):
    """The operation conflicts with current state (e.g. stale version)."""


class ValidationError(AppError):
    """The request is well-formed but violates a business rule."""
