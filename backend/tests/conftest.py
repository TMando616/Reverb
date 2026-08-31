"""Shared test fixtures.

DB-backed fixtures (transaction isolation via savepoints, design.md §13-1) are
added with the foundation spec. For the M0 scaffold we only exercise the app
wiring, so no database is required here.
"""

from collections.abc import AsyncIterator

import pytest
from app.main import create_app
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
