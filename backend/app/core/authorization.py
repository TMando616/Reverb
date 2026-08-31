"""Actor / Permission / Role and the project authorizer (design.md §5).

Stub for the M0 environment scaffold. ``core`` must not import ``app.modules``
(enforced by .importlinter); when the authorizer needs membership data it
receives it through a ``Protocol`` (design.md §5-2).
"""

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    REVIEWER = "reviewer"
