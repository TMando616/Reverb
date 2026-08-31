"""Dependency wiring for the auth module.

The assembly role: allowed to import both router-facing and repository-facing
code, so it is intentionally excluded from the layers contract (design.md §11).
"""
