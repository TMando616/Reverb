"""Persistence for the auth module — the only layer that talks to the DB.

Receives an `AsyncSession`; holds no business rules (ADR-0009).
"""
