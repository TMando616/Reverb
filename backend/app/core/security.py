"""Password hashing (Argon2id) and opaque session-token helpers.

- Passwords: Argon2id via ``argon2-cffi`` (design.md §4-2).
- Session token: opaque random string; only its sha256 is stored server-side
  (design.md §4-1). The raw token is returned to the client once.
"""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()

# Fixed Argon2id hash verified against when the email is unknown, so login
# spends the same CPU cost either way and timing can't reveal whether an
# address is registered (design.md §4-2). Computed once at import.
DUMMY_PASSWORD_HASH: str = _hasher.hash("reverb-nonexistent-account")


def hash_password(password: str) -> str:
    """Return an Argon2id hash for ``password``."""
    return _hasher.hash(password)


def verify_password(hashed: str, password: str) -> bool:
    """Return whether ``password`` matches ``hashed``. Never raises."""
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def generate_token() -> str:
    """Return a new opaque session token (URL-safe)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Return the sha256 hex digest stored in ``sessions.token_hash`` (design.md §4-1)."""
    return hashlib.sha256(token.encode()).hexdigest()
