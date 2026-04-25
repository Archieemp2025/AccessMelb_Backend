from collections import namedtuple
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.database import get_session

_SENTINEL = object()

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

# Realistic Google Places response shape, modelled on the actual response
# from Koorie Heritage Trust.
SAMPLE_GOOGLE_PLACES_RESPONSE = {
    "regularOpeningHours": {
        "openNow": False,
        "weekdayDescriptions": [
            "Monday: 10:00 AM – 5:00 PM",
            "Tuesday: 10:00 AM – 5:00 PM",
            "Wednesday: 10:00 AM – 5:00 PM",
            "Thursday: 10:00 AM – 5:00 PM",
            "Friday: 10:00 AM – 5:00 PM",
            "Saturday: 10:00 AM – 5:00 PM",
            "Sunday: 10:00 AM – 5:00 PM",
        ],
    },
    "accessibilityOptions": {
        "wheelchairAccessibleEntrance": True,
        "wheelchairAccessibleParking": True,
        "wheelchairAccessibleRestroom": True,
        # No wheelchairAccessibleSeating — Google doesn't always have all fields
    },
}


# Destination row that includes place_id, used by the detail endpoint
DestinationWithPlaceIdRow = namedtuple(
    "DestinationWithPlaceIdRow",
    ["destination_id", "feature_name", "category", "sub_theme", "place_id", "latitude", "longitude"],
)

SAMPLE_DESTINATION_WITH_PLACE_ID = DestinationWithPlaceIdRow(
    1, "Koorie Heritage Trust Inc", "gallery", "Art Gallery/Museum",
    "ChIJ5QD93bZC1moRepgdLPOmi4k", -37.81338543, 144.95402791,
)

SAMPLE_DESTINATION_WITHOUT_PLACE_ID = DestinationWithPlaceIdRow(
    2, "Some Venue", "library", "Library",
    None, -37.8100, 144.9650,
)

SAMPLE_DETAIL_DESTINATIONS = [
    DestinationWithPlaceIdRow(
        1, "National Gallery of Victoria", "gallery", "Art Gallery/Museum",
        "ChIJP7oRROtC1moRJVbY7zxMHPo", -37.8224, 144.9690,
    ),
]


def mock_fetch_venue_details(return_value=None, side_effect=None):
    """Patch the Google Places fetch function at its point of use in the routes module."""
    mock = AsyncMock()
    if side_effect is not None:
        mock.side_effect = side_effect
    else:
        mock.return_value = (
            return_value if return_value is not None else SAMPLE_GOOGLE_PLACES_RESPONSE
        )
    return patch("app.routes.destinations.fetch_venue_details", mock)


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

def mock_fetch_venue_details(return_value=_SENTINEL, side_effect=None):
    """Patch the Google Places fetch function at its point of use in the routes module."""
    mock = AsyncMock()
    if side_effect is not None:
        mock.side_effect = side_effect
    elif return_value is _SENTINEL:
        mock.return_value = SAMPLE_GOOGLE_PLACES_RESPONSE
    else:
        mock.return_value = return_value  # respects None when explicitly passed
    return patch("app.routes.destinations.fetch_venue_details", mock)