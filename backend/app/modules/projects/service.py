"""Business rules and authorization for the projects module (企画・メンバー・招待).

Knows nothing about HTTP (no `fastapi` / `Request`) and never holds an
`AsyncSession` directly — repositories are injected in (design.md §2-2).
"""
