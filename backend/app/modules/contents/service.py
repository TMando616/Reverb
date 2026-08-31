"""Business rules and authorization for the contents module (コンテンツ CRUD・状態遷移).

Knows nothing about HTTP (no `fastapi` / `Request`) and never holds an
`AsyncSession` directly — repositories are injected in (design.md §2-2).
"""
