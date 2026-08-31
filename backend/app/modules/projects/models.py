"""ORM models for the projects module (企画・メンバー・招待).

Tables land here in the foundation spec (design.md §3). Only this file and
repository.py may import `sqlalchemy` inside a module.
"""

from app.core.db import Base  # noqa: F401  (re-exported for models to subclass)
