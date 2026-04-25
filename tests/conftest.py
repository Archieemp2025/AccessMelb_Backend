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


# Realistic OTP response shape, based on the actual Footscray to Flinders
# response captured during OpenTripPlanner UI testing. Keeping the sample
# close to real OTP output means tests catch changes to the transformer
# or enrichments.
SAMPLE_OTP_ITINERARY = {
    "duration": 2403,
    "walkDistance": 1251.07,
    "startTime": 1745491544000, # milliseconds UTC
    "endTime": 1745493947000,
    "legs": [
        {
            "mode": "WALK",
            "startTime": 1745491544000,
            "endTime": 1745492040000,
            "duration": 496,
            "distance": 325.4,
            "from": {
                "name": "Origin",
                "lat": -37.8008,
                "lon": 144.9033,
                "stop": None,
            },
            "to": {
                "name": "Footscray Station",
                "lat": -37.8017184,
                "lon": 144.902443,
                "stop": {
                    "gtfsId": "2:26508",
                    "wheelchairBoarding": "POSSIBLE",
                    "platformCode": "5",
                    "parentStation": {"name": "Footscray Railway Station"},
                },
            },
            "route": None,
            "trip": None,
            "intermediateStops": None,
            "legGeometry": {"points": "d~ueFwllsZ~CxG"},
        },
        {
            "mode": "RAIL",
            "startTime": 1745492040000,
            "endTime": 1745492580000,
            "duration": 540,
            "distance": 7348.51,
            "from": {
                "name": "Footscray Station",
                "lat": -37.8017184,
                "lon": 144.902443,
                "stop": {
                    "gtfsId": "2:26508",
                    "wheelchairBoarding": "POSSIBLE",
                    "platformCode": "5",
                    "parentStation": {"name": "Footscray Railway Station"},
                },
            },
            "to": {
                "name": "Southern Cross Station",
                "lat": -37.8186635,
                "lon": 144.951766,
                "stop": {
                    "gtfsId": "2:22192",
                    "wheelchairBoarding": "POSSIBLE",
                    "platformCode": "13",
                    "parentStation": {"name": "Southern Cross Railway Station"},
                },
            },
            "route": {
                "shortName": "Williamstown",
                "longName": "Williamstown - City",
                "agency": {"name": "Transport Victoria"},
                "mode": "RAIL",
            },
            "trip": {
                "tripHeadsign": "Flinders Street",
                "wheelchairAccessible": "POSSIBLE",
            },
            "intermediateStops": [
                {
                    "gtfsId": "2:15522",
                    "name": "South Kensington Station",
                    "wheelchairBoarding": "POSSIBLE",
                },
            ],
            "legGeometry": {"points": "|cveFkglsZ_AeAa@i@"},
        },
        {
            "mode": "WALK",
            "startTime": 1745492580000,
            "endTime": 1745493947000,
            "duration": 1367,
            "distance": 925.67,
            "from": {
                "name": "Southern Cross Station",
                "lat": -37.8186635,
                "lon": 144.951766,
                "stop": {
                    "gtfsId": "2:22192",
                    "wheelchairBoarding": "POSSIBLE",
                    "platformCode": "13",
                    "parentStation": {"name": "Southern Cross Railway Station"},
                },
            },
            "to": {
                "name": "Destination",
                "lat": -37.8133854,
                "lon": 144.9540279,
                "stop": None,
            },
            "route": None,
            "trip": None,
            "intermediateStops": None,
            "legGeometry": {"points": "tmyeFo{usZ@@kClB"},
        },
    ],
}

# Realistic stopsByRadius response, modelled on the Koorie Heritage Trust
# result from CURL Testing. Includes mode diversity (tram + bus),
# the duplicate-same-name pattern that dedup needs to handle, and the
# typical NO_INFORMATION wheelchair boarding from Victoria's GTFS feed.
SAMPLE_STOPS_BY_RADIUS_EDGES = [
    {
        "node": {
            "stop": {
                "gtfsId": "3:19549",
                "name": "King St/Lonsdale St",
                "lat": -37.8142881,
                "lon": 144.9551244,
                "wheelchairBoarding": "NO_INFORMATION",
                "vehicleMode": "BUS",
                "parentStation": None,
                "routes": [
                    {"shortName": "302", "longName": "Route 302", "mode": "BUS"},
                    {"shortName": "216", "longName": "Route 216", "mode": "BUS"},
                    {"shortName": "906", "longName": "Route 906", "mode": "BUS"},
                ],
            },
            "distance": 168,
        }
    },
    {
        "node": {
            "stop": {
                "gtfsId": "1:46863",
                "name": "Spencer St/La Trobe St #1",
                "lat": -37.812883,
                "lon": 144.9525733,
                "wheelchairBoarding": "NO_INFORMATION",
                "vehicleMode": "TRAM",
                "parentStation": None,
                "routes": [
                    {"shortName": "86", "longName": "Route 86", "mode": "TRAM"},
                    {"shortName": "30", "longName": "Route 30", "mode": "TRAM"},
                ],
            },
            "distance": 207,
        }
    },
    {
        "node": {
            "stop": {
                "gtfsId": "3:19547",
                "name": "Lonsdale St/Spencer St",
                "lat": -37.8148209,
                "lon": 144.9520767,
                "wheelchairBoarding": "NO_INFORMATION",
                "vehicleMode": "BUS",
                "parentStation": None,
                "routes": [
                    {"shortName": "216", "longName": "Route 216", "mode": "BUS"},
                ],
            },
            "distance": 291,
        }
    },
]

DestinationCoordinates = namedtuple("DestinationCoordinates", ["latitude", "longitude"])

# Destination ID 1 lives at these coordinates in this mock. Matches the
# sample destinations above.
SAMPLE_DESTINATION_COORDS = DestinationCoordinates(-37.8133854, 144.9540279)
# Walking leg template for a stop-to-destination walk. Real OTP response
# shape, duration and distance vary per call, but the surrounding structure
# stays consistent.
SAMPLE_WALKING_LEG = {
    "mode": "WALK",
    "duration": 239,
    "distance": 169.25,
    "legGeometry": {"points": "jmxeF}ivsZG[COFCGYEOFCdC"},
}
# Full destination row for fallback endpoint, includes name and category
# which the plan endpoint doesn't need.
FallbackDestinationRow = namedtuple(
    "FallbackDestinationRow",
    ["destination_id", "feature_name", "category", "latitude", "longitude"],
)

SAMPLE_FALLBACK_DESTINATION = FallbackDestinationRow(
    1, "Koorie Heritage Trust Inc", "gallery", -37.8133854, 144.9540279,
)

def mock_plan_journey(return_value=None, side_effect=None):
    """Patch the OTP plan_journey function.

    Use as a context manager. Returns the AsyncMock so individual tests
    can assert on call arguments if needed.

    - return_value: the itinerary dict to return
    - side_effect: use instead of return_value to raise an exception
    """
    # Patch at the point of use (in the routes module), not where it's
    # defined (in the services module). This is the standard pytest-mock
    # pattern, it replaces the reference the route handler actually uses.
    mock = AsyncMock()
    if side_effect is not None:
        mock.side_effect = side_effect
    else:
        mock.return_value = return_value or SAMPLE_OTP_ITINERARY

    return patch("app.routes.journeys.plan_journey", mock)


def mock_destination_lookup(coords=None):
    """Build a mock session that returns destination coordinates.

    Used for journey tests that need to succeed the destination lookup
    before reaching the OTP call.
    """
    if coords is None:
        coords = SAMPLE_DESTINATION_COORDS
    return create_mock_session(execute_results=[[coords]])


def mock_destination_not_found():
    """Build a mock session where destination lookup returns no rows."""
    return create_mock_session(execute_results=[[]])

def mock_find_stops_by_radius(edges=None):
    """Patch the stops-by-radius OTP call at its point of use in the routes module."""
    mock = AsyncMock()
    mock.return_value = edges if edges is not None else SAMPLE_STOPS_BY_RADIUS_EDGES
    return patch("app.routes.journeys.find_stops_by_radius", mock)

def mock_walk_to_stop(walking_leg=None, side_effect=None):
    """Patch the walking-route OTP call at its point of use in the routes module."""
    mock = AsyncMock()
    if side_effect is not None:
        mock.side_effect = side_effect
    else:
        mock.return_value = walking_leg if walking_leg is not None else SAMPLE_WALKING_LEG
    return patch("app.routes.journeys.walk_to_stop", mock)

def mock_fallback_destination_lookup(dest_row=None):
    """Mock session that returns a full destination row (with name and category)."""
    if dest_row is None:
        dest_row = SAMPLE_FALLBACK_DESTINATION
    return create_mock_session(execute_results=[[dest_row]])
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
