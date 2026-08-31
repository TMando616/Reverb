"""Password hashing and opaque token generation/verification.

Stub for the M0 environment scaffold. The concrete hash algorithm and token
format are decided in the ``foundation`` spec (design.md §4-1 / §4-2); this
module exists so the layout and import contracts are in place.
"""

import secrets


def generate_token() -> str:
    """Return a new opaque session token (URL-safe)."""
    return secrets.token_urlsafe(32)
