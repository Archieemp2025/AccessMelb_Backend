"""Tests for POST /api/v1/journeys/plan-accessible endpoint.

The plan-accessible endpoint selects the best OTP itinerary based on
last-walking-leg steepness. These tests mock the database (destination
lookups + footpath_steepness queries) and OTP (multiple itineraries).
Real OTP and real database connections are never touched.

Test strategy:
- Correct path: response shape, journey fields match /plan output
- Steepness selection: within-standard picks fastest, all-exceed picks flattest
- Polyline decoding: verify decoder handles real OTP polylines
- Edge cases: no steepness data, no last walk leg, single itinerary
- Validation: same schema as /plan (origin bounds, destination_id required)
- OTP failures: 404 for no journey, 503 for transport errors
- Warning: all_exceed_standard triggers user-facing warning text
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException

from tests.conftest import (
    override_session,
    mock_destination_lookup,
    mock_destination_not_found,
    SAMPLE_OTP_ITINERARY,
    SAMPLE_DESTINATION_COORDS,
)


VALID_REQUEST_BODY = {
    "origin": {"lat": -37.8008, "lon": 144.9033},
    "destination_id": 1,
}


def _make_itinerary(duration: int, last_walk_polyline: str = "d~ueFwllsZ~CxG") -> dict:
    """Build a minimal OTP itinerary with configurable duration and last walk polyline."""
    return {
        "duration": duration,
        "walkDistance": 500.0,
        "startTime": 1745491544000,
        "endTime": 1745491544000 + (duration * 1000),
        "legs": [
            {
                "mode": "WALK",
                "startTime": 1745491544000,
                "endTime": 1745491744000,
                "duration": 200,
                "distance": 150.0,
                "from": {"name": "Origin", "lat": -37.8008, "lon": 144.9033, "stop": None},
                "to": {
                    "name": "Some Station",
                    "lat": -37.8050, "lon": 144.9100,
                    "stop": {
                        "gtfsId": "2:12345",
                        "wheelchairBoarding": "POSSIBLE",
                        "platformCode": "1",
                        "parentStation": {"name": "Some Railway Station"},
                    },
                },
                "route": None,
                "trip": None,
                "intermediateStops": None,
                "legGeometry": {"points": "d~ueFwllsZ~CxG"},
            },
            {
                "mode": "RAIL",
                "startTime": 1745491744000,
                "endTime": 1745492344000,
                "duration": 600,
                "distance": 5000.0,
                "from": {
                    "name": "Some Station",
                    "lat": -37.8050, "lon": 144.9100,
                    "stop": {
                        "gtfsId": "2:12345",
                        "wheelchairBoarding": "POSSIBLE",
                        "platformCode": "1",
                        "parentStation": {"name": "Some Railway Station"},
                    },
                },
                "to": {
                    "name": "City Station",
                    "lat": -37.8180, "lon": 144.9520,
                    "stop": {
                        "gtfsId": "2:22192",
                        "wheelchairBoarding": "POSSIBLE",
                        "platformCode": "5",
                        "parentStation": {"name": "City Railway Station"},
                    },
                },
                "route": {
                    "shortName": "TestLine",
                    "longName": "Test - City",
                    "agency": {"name": "Transport Victoria"},
                    "mode": "RAIL",
                },
                "trip": {
                    "tripHeadsign": "Flinders Street",
                    "wheelchairAccessible": "POSSIBLE",
                },
                "intermediateStops": [],
                "legGeometry": {"points": "|cveFkglsZ_AeAa@i@"},
            },
            {
                "mode": "WALK",
                "startTime": 1745492344000,
                "endTime": 1745492544000,
                "duration": 200,
                "distance": 168.0,
                "from": {
                    "name": "City Station",
                    "lat": -37.8180, "lon": 144.9520,
                    "stop": {
                        "gtfsId": "2:22192",
                        "wheelchairBoarding": "POSSIBLE",
                        "platformCode": "5",
                        "parentStation": {"name": "City Railway Station"},
                    },
                },
                "to": {
                    "name": "Destination",
                    "lat": -37.8133854, "lon": 144.9540279,
                    "stop": None,
                },
                "route": None,
                "trip": None,
                "intermediateStops": None,
                "legGeometry": {"points": last_walk_polyline},
            },
        ],
    }


def mock_fetch_multiple_itineraries(itineraries=None, side_effect=None):
    """Patch the _fetch_multiple_itineraries function at its point of use."""
    mock = AsyncMock()
    if side_effect is not None:
        mock.side_effect = side_effect
    else:
        mock.return_value = itineraries or [SAMPLE_OTP_ITINERARY]
    return patch("app.services.route_steepness._fetch_multiple_itineraries", mock)


def mock_compute_steepness(gradients: list):
    """Patch _compute_steepness to return predetermined gradient values.

    gradients: list of floats or Nones, one per itinerary.
    Each call to _compute_steepness returns the next value in the list.
    """
    mock = AsyncMock()
    mock.side_effect = gradients
    return patch("app.services.route_steepness._compute_steepness", mock)


@pytest.mark.asyncio
async def test_plan_accessible_returns_200(client):
    """A valid request with a known destination returns 200."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(), \
         mock_compute_steepness([3.2]):
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_plan_accessible_response_shape(client):
    """Response contains journey, last_walk_steepness, all_exceed_standard, and warning."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(), \
         mock_compute_steepness([3.2]):
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    assert "journey" in data
    assert "last_walk_steepness" in data
    assert "all_exceed_standard" in data
    assert "warning" in data


@pytest.mark.asyncio
async def test_journey_field_matches_plan_response_shape(client):
    """The journey field has the same structure as /journeys/plan response."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(), \
         mock_compute_steepness([3.2]):
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    journey = response.json()["journey"]
    for field in [
        "duration_seconds", "walk_distance_metres", "start_time",
        "end_time", "transfers", "legs", "accessibility_summary",
    ]:
        assert field in journey, f"Missing field in journey: {field}"


@pytest.mark.asyncio
async def test_last_walk_steepness_shape(client):
    """last_walk_steepness contains max_gradient_percent and within_standard."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(), \
         mock_compute_steepness([4.2]):
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    steepness = response.json()["last_walk_steepness"]
    assert "max_gradient_percent" in steepness
    assert "within_standard" in steepness

@pytest.mark.asyncio
async def test_selects_fastest_when_within_standard(client):
    """When multiple routes are within 5%, the fastest is selected."""
    override_session(mock_destination_lookup())

    itineraries = [
        _make_itinerary(duration=2400),  # slower, 3.0%
        _make_itinerary(duration=1800),  # faster, 4.5%
        _make_itinerary(duration=2000),  # mid, 2.1%
    ]

    with mock_fetch_multiple_itineraries(itineraries), \
         mock_compute_steepness([3.0, 4.5, 2.1]):
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    # Fastest within standard is the 1800s itinerary
    assert data["journey"]["duration_seconds"] == 1800
    assert data["last_walk_steepness"]["within_standard"] is True
    assert data["all_exceed_standard"] is False
    assert data["warning"] is None


@pytest.mark.asyncio
async def test_selects_flattest_when_all_exceed_standard(client):
    """When all routes exceed 5%, the one with the lowest gradient is selected."""
    override_session(mock_destination_lookup())

    itineraries = [
        _make_itinerary(duration=1800),  # fastest, 8.5%
        _make_itinerary(duration=2400),  # slowest, 6.2%
        _make_itinerary(duration=2000),  # mid, 7.0%
    ]

    with mock_fetch_multiple_itineraries(itineraries), \
         mock_compute_steepness([8.5, 6.2, 7.0]):
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    # Flattest is 6.2% (duration 2400s)
    assert data["journey"]["duration_seconds"] == 2400
    assert data["last_walk_steepness"]["max_gradient_percent"] == 6.2
    assert data["last_walk_steepness"]["within_standard"] is False
    assert data["all_exceed_standard"] is True
    assert data["warning"] is not None
    assert "6.2%" in data["warning"]


@pytest.mark.asyncio
async def test_prefers_within_standard_over_faster_exceeding(client):
    """A slower route within standard is preferred over a faster one exceeding it."""
    override_session(mock_destination_lookup())

    itineraries = [
        _make_itinerary(duration=1500),  # fastest, but 7.0%
        _make_itinerary(duration=2500),  # slowest, but 3.2%
    ]

    with mock_fetch_multiple_itineraries(itineraries), \
         mock_compute_steepness([7.0, 3.2]):
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    # Should pick the 2500s route (within standard) over the 1500s route
    assert data["journey"]["duration_seconds"] == 2500
    assert data["last_walk_steepness"]["within_standard"] is True
    assert data["all_exceed_standard"] is False


@pytest.mark.asyncio
async def test_no_steepness_data_returns_fastest(client):
    """When no footpath data exists, the fastest route is returned without warning."""
    override_session(mock_destination_lookup())

    itineraries = [
        _make_itinerary(duration=2400),
        _make_itinerary(duration=1800),
    ]

    with mock_fetch_multiple_itineraries(itineraries), \
         mock_compute_steepness([None, None]):
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    assert data["journey"]["duration_seconds"] == 1800
    assert data["last_walk_steepness"]["max_gradient_percent"] is None
    assert data["last_walk_steepness"]["within_standard"] is None
    assert data["all_exceed_standard"] is False
    assert data["warning"] is None

@pytest.mark.asyncio
async def test_warning_includes_threshold_and_gradient(client):
    """The warning text mentions both the standard threshold and the selected gradient."""
    override_session(mock_destination_lookup())

    itineraries = [_make_itinerary(duration=2000)]

    with mock_fetch_multiple_itineraries(itineraries), \
         mock_compute_steepness([9.3]):
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    warning = response.json()["warning"]
    assert "5.0%" in warning
    assert "9.3%" in warning


@pytest.mark.asyncio
async def test_no_warning_when_within_standard(client):
    """No warning is returned when the selected route is within standard."""
    override_session(mock_destination_lookup())

    itineraries = [_make_itinerary(duration=2000)]

    with mock_fetch_multiple_itineraries(itineraries), \
         mock_compute_steepness([3.5]):
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    assert response.json()["warning"] is None
    assert response.json()["all_exceed_standard"] is False


@pytest.mark.asyncio
async def test_reject_origin_outside_melbourne_bounds(client):
    """Coordinates outside Greater Melbourne are rejected at the schema layer."""
    response = await client.post(
        "/api/v1/journeys/plan-accessible",
        json={"origin": {"lat": 51.5074, "lon": -0.1278}, "destination_id": 1},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_missing_origin(client):
    """Request without origin fails validation."""
    response = await client.post(
        "/api/v1/journeys/plan-accessible",
        json={"destination_id": 1},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_missing_destination_id(client):
    """Request without destination_id fails validation."""
    response = await client.post(
        "/api/v1/journeys/plan-accessible",
        json={"origin": {"lat": -37.8008, "lon": 144.9033}},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_zero_destination_id(client):
    """destination_id=0 fails validation (must be >= 1)."""
    response = await client.post(
        "/api/v1/journeys/plan-accessible",
        json={"origin": {"lat": -37.8008, "lon": 144.9033}, "destination_id": 0},
    )
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_destination_not_found_returns_404(client):
    """If the destination ID doesn't exist in the database, return 404."""
    override_session(mock_destination_not_found())

    response = await client.post(
        "/api/v1/journeys/plan-accessible",
        json=VALID_REQUEST_BODY,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Destination not found"


@pytest.mark.asyncio
async def test_otp_no_journey_found_returns_404(client):
    """When OTP can't find an accessible journey, return 404."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(side_effect=HTTPException(
        status_code=404,
        detail="No accessible journey found for this route and time. "
               "Services may not be running, or accessibility constraints "
               "may prevent a valid route.",
    )):
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    assert response.status_code == 404
    assert "No accessible journey" in response.json()["detail"]


@pytest.mark.asyncio
async def test_otp_unavailable_returns_503(client):
    """When OTP is unreachable, return 503 with a generic message."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(side_effect=HTTPException(
        status_code=503,
        detail="Journey planning is currently unavailable. Please try again shortly.",
    )):
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    assert response.status_code == 503

@pytest.mark.asyncio
async def test_polyline_decoder_returns_correct_coordinates():
    """The polyline decoder produces valid lon/lat pairs from a real OTP polyline."""
    from app.services.route_steepness import _decode_polyline

    # This is the last walk leg polyline from the sample OTP response
    points = _decode_polyline("tmyeFo{usZ@@kClB")
    assert len(points) >= 2

    # Points should be (lon, lat) order for PostGIS
    for lon, lat in points:
        # Should be in Melbourne area
        assert 144.0 < lon < 146.0, f"Longitude out of range: {lon}"
        assert -38.5 < lat < -37.0, f"Latitude out of range: {lat}"


@pytest.mark.asyncio
async def test_polyline_decoder_empty_string():
    """Empty polyline returns an empty list."""
    from app.services.route_steepness import _decode_polyline

    points = _decode_polyline("")
    assert points == []

@pytest.mark.asyncio
async def test_extract_last_walk_leg_finds_final_walk():
    """The extractor finds the last WALK leg where to.stop is None."""
    from app.services.route_steepness import _extract_last_walk_leg

    leg = _extract_last_walk_leg(SAMPLE_OTP_ITINERARY)
    assert leg is not None
    assert leg["mode"] == "WALK"
    assert leg["to"]["stop"] is None
    assert leg["to"]["name"] == "Destination"


@pytest.mark.asyncio
async def test_extract_last_walk_leg_returns_none_for_no_legs():
    """An itinerary with no legs returns None."""
    from app.services.route_steepness import _extract_last_walk_leg

    result = _extract_last_walk_leg({"legs": []})
    assert result is None


@pytest.mark.asyncio
async def test_extract_last_walk_leg_returns_none_for_transit_only():
    """An itinerary ending with a transit leg (no final walk) returns None."""
    from app.services.route_steepness import _extract_last_walk_leg

    itinerary = {
        "legs": [{
            "mode": "RAIL",
            "to": {
                "name": "Station",
                "stop": {"gtfsId": "2:123", "wheelchairBoarding": "POSSIBLE"},
            },
        }],
    }

    result = _extract_last_walk_leg(itinerary)
    assert result is None

@pytest.mark.asyncio
async def test_single_itinerary_within_standard(client):
    """When OTP returns only 1 itinerary and it's within standard, select it."""
    override_session(mock_destination_lookup())

    itineraries = [_make_itinerary(duration=2000)]

    with mock_fetch_multiple_itineraries(itineraries), \
         mock_compute_steepness([4.0]):
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    assert data["journey"]["duration_seconds"] == 2000
    assert data["last_walk_steepness"]["max_gradient_percent"] == 4.0
    assert data["last_walk_steepness"]["within_standard"] is True
    assert data["all_exceed_standard"] is False


@pytest.mark.asyncio
async def test_single_itinerary_exceeds_standard(client):
    """When OTP returns only 1 itinerary and it exceeds standard, select it with warning."""
    override_session(mock_destination_lookup())

    itineraries = [_make_itinerary(duration=2000)]

    with mock_fetch_multiple_itineraries(itineraries), \
         mock_compute_steepness([8.0]):
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    assert data["journey"]["duration_seconds"] == 2000
    assert data["last_walk_steepness"]["max_gradient_percent"] == 8.0
    assert data["all_exceed_standard"] is True
    assert data["warning"] is not None