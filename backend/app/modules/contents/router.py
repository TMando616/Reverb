"""HTTP controller for the contents module — DTO validation and status codes only.

No business decisions here; those live in service.py (ADR-0009).
"""

from fastapi import APIRouter

router = APIRouter(prefix="/contents", tags=["contents"])
