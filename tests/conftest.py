from collections import namedtuple
from unittest.mock import AsyncMock

import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session


DestinationRow = namedtuple(
    "DestinationRow",
    ["destination_id", "feature_name", "category", "sub_theme", "latitude", "longitude"],
)

ToiletRow = namedtuple(
    "ToiletRow",
    ["toilet_id", "name", "wheelchair_accessible", "distance_m", "latitude", "longitude"],
)

SAMPLE_DESTINATIONS = [
    DestinationRow(1, "National Gallery of Victoria", "gallery", "Art Gallery/Museum", -37.8224, 144.9690),
    DestinationRow(2, "State Library Victoria", "library", "Library", -37.8098, 144.9652),
    DestinationRow(3, "Arts Centre Melbourne", "theatre", "Theatre Live", -37.8214, 144.9684),
]

SAMPLE_TOILETS = [
    ToiletRow(1, "Toilet 4 — Market Street", "yes", 120.3, -37.8175, 144.9603),
    ToiletRow(2, "Toilet 11 — Lonsdale Street", "yes", 340.5, -37.8100, 144.9699),
]


class MockResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


def create_mock_session(scalar_value=0, execute_results=None):
    session = AsyncMock()
    session.scalar.return_value = scalar_value

    if execute_results is not None:
        session.execute.side_effect = [MockResult(rows) for rows in execute_results]
    else:
        session.execute.return_value = MockResult([])

    return session


def override_session(session):
    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()