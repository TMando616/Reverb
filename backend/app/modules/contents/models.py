"""ORM models for the contents module (コンテンツ CRUD・状態遷移).

Tables land here in the foundation spec (design.md §3). Only this file and
repository.py may import `sqlalchemy` inside a module.
"""

from app.core.db import Base  # noqa: F401  (re-exported for models to subclass)
