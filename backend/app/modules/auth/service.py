"""Business rules and authorization for the auth module (認証・現在のユーザー解決).

Knows nothing about HTTP (no `fastapi` / `Request`) and never holds an
`AsyncSession` directly — repositories are injected in (design.md §2-2).
"""
