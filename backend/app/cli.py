"""Management commands that bypass HTTP (design.md §9-0).

Used to bootstrap the first user and the demo account. Allowed to touch
``AsyncSession`` directly (see .importlinter allow-list). Implemented in the
``foundation`` spec; this file reserves the entry point.
"""

from __future__ import annotations


def main() -> None:  # pragma: no cover - filled in by the foundation spec
    raise SystemExit("cli not implemented yet — see .kiro/specs/foundation")


if __name__ == "__main__":
    main()
