"""ORM models for the auth module (認証・現在のユーザー解決).

Tables land here in the foundation spec (design.md §3). Only this file and
repository.py may import `sqlalchemy` inside a module.
"""

from app.core.db import Base  # noqa: F401  (re-exported for models to subclass)
