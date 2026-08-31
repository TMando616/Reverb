"""HTTP controller for the auth module — DTO validation and status codes only.

No business decisions here; those live in service.py (ADR-0009).
"""

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])
