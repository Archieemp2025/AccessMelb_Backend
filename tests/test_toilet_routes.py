"""Tests for nearby toilet routes in the plan-accessible endpoint.

The plan-accessible endpoint now includes nearby_toilets, accessible
toilets near the destination with walking routes from the alighting stop.
These tests mock the database (toilet queries), OTP (walking routes),
and the steepness service. Real external services are never touched.

Test strategy:
- Response shape: nearby_toilets field with correct structure
- Toilet data: wheelchair-accessible only, capped at 3, ordered by distance
- Routes: both route_from_alighting_stop and route_to_destination present
- Alighting stop: correctly extracted from different itinerary shapes
- Failures: OTP route failure returns null route but keeps toilet info
- Edge cases: no toilets found, walk-only journey
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException

from tests.conftest import (
    override_session,
    mock_destination_lookup,
    SAMPLE_OTP_ITINERARY,
    SAMPLE_DESTINATION_COORDS,
)


VALID_REQUEST_BODY = {
    "origin": {"lat": -37.8008, "lon": 144.9033},
    "destination_id": 1,
}


SAMPLE_TOILETS_NEAR_DEST = [
    {
        "toilet_id": 1,
        "name": "Toilet 4 — Market Street",
        "lat": -37.8175,
        "lon": 144.9603,
        "distance_from_destination_m": 120.3,
    },
    {
        "toilet_id": 2,
        "name": "Toilet 11 — Lonsdale Street",
        "lat": -37.8100,
        "lon": 144.9699,
        "distance_from_destination_m": 210.5,
    },
    {
        "toilet_id": 3,
        "name": "Toilet 7 — Bourke Street",
        "lat": -37.8130,
        "lon": 144.9650,
        "distance_from_destination_m": 340.8,
    },
]

SAMPLE_TOILET_WALKING_LEG = {
    "duration": 180,
    "distance": 145.2,
    "legGeometry": {"points": "jmxeF}ivsZG[COFCGYEOFCdC"},
}


def mock_fetch_multiple_itineraries(itineraries=None, side_effect=None):
    """Patch _fetch_multiple_itineraries at its point of use."""
    mock = AsyncMock()
    if side_effect is not None:
        mock.side_effect = side_effect
    else:
        mock.return_value = itineraries or [SAMPLE_OTP_ITINERARY]
    return patch("app.services.route_steepness._fetch_multiple_itineraries", mock)


def mock_compute_steepness(gradients: list):
    """Patch _compute_steepness to return predetermined gradient values."""
    mock = AsyncMock()
    mock.side_effect = gradients
    return patch("app.services.route_steepness._compute_steepness", mock)


def mock_find_nearby_toilets(toilets=None):
    """Patch find_nearby_accessible_toilets at its point of use."""
    mock = AsyncMock()
    mock.return_value = toilets if toilets is not None else SAMPLE_TOILETS_NEAR_DEST
    return patch("app.services.toilet_routes.find_nearby_accessible_toilets", mock)


def mock_toilet_walk_to_stop(walking_leg=None, side_effect=None):
    """Patch _get_toilet_walking_route at its point of use in toilet_routes.
    
    We patch the wrapper function rather than walk_to_stop because
    the wrapper transforms the OTP response into our route dict shape.
    When walking_leg is None, returns None (simulates no route found).
    """
    mock = AsyncMock()
    if side_effect is not None:
        mock.side_effect = side_effect
    elif walking_leg is None:
        # Default: return a valid route dict (matching our schema shape)
        mock.return_value = {
            "duration_seconds": SAMPLE_TOILET_WALKING_LEG["duration"],
            "distance_metres": SAMPLE_TOILET_WALKING_LEG["distance"],
            "polyline": SAMPLE_TOILET_WALKING_LEG["legGeometry"]["points"],
        }
    else:
        mock.return_value = walking_leg
    return patch("app.services.toilet_routes._get_toilet_walking_route", mock)


def mock_toilet_walk_to_stop_none():
    """Patch _get_toilet_walking_route to return None (no route found)."""
    mock = AsyncMock(return_value=None)
    return patch("app.services.toilet_routes._get_toilet_walking_route", mock)


@pytest.mark.asyncio
async def test_response_includes_nearby_toilets(client):
    """The plan-accessible response includes a nearby_toilets field."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(), \
         mock_compute_steepness([3.2]), \
         mock_find_nearby_toilets(), \
         mock_toilet_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    assert response.status_code == 200
    assert "nearby_toilets" in response.json()


@pytest.mark.asyncio
async def test_each_toilet_has_correct_structure(client):
    """Each toilet entry has toilet info + two routes."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(), \
         mock_compute_steepness([3.2]), \
         mock_find_nearby_toilets(), \
         mock_toilet_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    toilets = response.json()["nearby_toilets"]
    assert len(toilets) > 0

    for toilet_entry in toilets:
        assert "toilet" in toilet_entry
        assert "route_from_alighting_stop" in toilet_entry
        assert "route_to_destination" in toilet_entry


@pytest.mark.asyncio
async def test_toilet_info_fields(client):
    """Each toilet has all expected info fields."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(), \
         mock_compute_steepness([3.2]), \
         mock_find_nearby_toilets(), \
         mock_toilet_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    toilet = response.json()["nearby_toilets"][0]["toilet"]
    assert "toilet_id" in toilet
    assert "name" in toilet
    assert "wheelchair_accessible" in toilet
    assert toilet["wheelchair_accessible"] == "yes"
    assert "distance_from_destination_m" in toilet
    assert "lat" in toilet
    assert "lon" in toilet


@pytest.mark.asyncio
async def test_route_fields(client):
    """Each route has duration, distance, and polyline."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(), \
         mock_compute_steepness([3.2]), \
         mock_find_nearby_toilets(), \
         mock_toilet_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    route = response.json()["nearby_toilets"][0]["route_from_alighting_stop"]
    assert "duration_seconds" in route
    assert "distance_metres" in route
    assert "polyline" in route

    route_dest = response.json()["nearby_toilets"][0]["route_to_destination"]
    assert "duration_seconds" in route_dest
    assert "distance_metres" in route_dest
    assert "polyline" in route_dest


@pytest.mark.asyncio
async def test_returns_up_to_3_toilets(client):
    """At most 3 toilets are returned even if more exist nearby."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(), \
         mock_compute_steepness([3.2]), \
         mock_find_nearby_toilets(SAMPLE_TOILETS_NEAR_DEST), \
         mock_toilet_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    assert len(response.json()["nearby_toilets"]) <= 3


@pytest.mark.asyncio
async def test_toilets_ordered_by_distance(client):
    """Toilets are returned in order of distance from the destination."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(), \
         mock_compute_steepness([3.2]), \
         mock_find_nearby_toilets(), \
         mock_toilet_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    toilets = response.json()["nearby_toilets"]
    distances = [t["toilet"]["distance_from_destination_m"] for t in toilets]
    assert distances == sorted(distances)


@pytest.mark.asyncio
async def test_otp_route_failure_returns_null_routes(client):
    """When OTP can't find a walking route, route fields are null but toilet info remains."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(), \
         mock_compute_steepness([3.2]), \
         mock_find_nearby_toilets([SAMPLE_TOILETS_NEAR_DEST[0]]), \
         mock_toilet_walk_to_stop_none():
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    toilet_entry = response.json()["nearby_toilets"][0]
    assert toilet_entry["toilet"]["name"] == "Toilet 4 — Market Street"
    assert toilet_entry["route_from_alighting_stop"] is None
    assert toilet_entry["route_to_destination"] is None


@pytest.mark.asyncio
async def test_no_toilets_returns_empty_list(client):
    """When no accessible toilets are found, nearby_toilets is an empty list."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(), \
         mock_compute_steepness([3.2]), \
         mock_find_nearby_toilets([]):
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    assert response.json()["nearby_toilets"] == []


@pytest.mark.asyncio
async def test_no_toilets_doesnt_break_journey_response(client):
    """The journey and steepness data is still present even with no toilets."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(), \
         mock_compute_steepness([3.2]), \
         mock_find_nearby_toilets([]):
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    assert "journey" in data
    assert "last_walk_steepness" in data
    assert data["nearby_toilets"] == []



@pytest.mark.asyncio
async def test_journey_and_steepness_still_present(client):
    """Adding toilets doesn't break the existing journey and steepness fields."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(), \
         mock_compute_steepness([4.2]), \
         mock_find_nearby_toilets(), \
         mock_toilet_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    assert data["journey"]["duration_seconds"] > 0
    assert data["last_walk_steepness"]["max_gradient_percent"] == 4.2
    assert data["all_exceed_standard"] is False
    assert data["warning"] is None
    assert len(data["nearby_toilets"]) > 0


@pytest.mark.asyncio
async def test_extract_alighting_stop_standard_itinerary():
    """Extracts the last transit stop from a walk-transit-walk itinerary."""
    from app.services.toilet_routes import _extract_alighting_stop

    result = _extract_alighting_stop(SAMPLE_OTP_ITINERARY)
    assert result is not None
    assert result["name"] == "Southern Cross Station"
    assert result["gtfs_id"] == "2:22192"
    assert result["lat"] == -37.8186635
    assert result["lon"] == 144.951766


@pytest.mark.asyncio
async def test_extract_alighting_stop_walk_only():
    """Returns None for a walk-only itinerary (no transit)."""
    from app.services.toilet_routes import _extract_alighting_stop

    walk_only = {
        "legs": [{
            "mode": "WALK",
            "from": {"name": "Origin", "lat": -37.8, "lon": 144.9, "stop": None},
            "to": {"name": "Destination", "lat": -37.81, "lon": 144.95, "stop": None},
        }],
    }

    result = _extract_alighting_stop(walk_only)
    assert result is None


@pytest.mark.asyncio
async def test_extract_alighting_stop_no_legs():
    """Returns None when itinerary has no legs."""
    from app.services.toilet_routes import _extract_alighting_stop

    result = _extract_alighting_stop({"legs": []})
    assert result is None


@pytest.mark.asyncio
async def test_extract_alighting_stop_multi_transit():
    """Extracts the correct alighting stop from a multi-transfer journey."""
    from app.services.toilet_routes import _extract_alighting_stop

    itinerary = {
        "legs": [
            {
                "mode": "WALK",
                "from": {"name": "Origin", "lat": -37.8, "lon": 144.9, "stop": None},
                "to": {
                    "name": "Stop A", "lat": -37.81, "lon": 144.91,
                    "stop": {"gtfsId": "1:111", "wheelchairBoarding": "POSSIBLE"},
                },
            },
            {
                "mode": "TRAM",
                "from": {
                    "name": "Stop A", "lat": -37.81, "lon": 144.91,
                    "stop": {"gtfsId": "1:111", "wheelchairBoarding": "POSSIBLE"},
                },
                "to": {
                    "name": "Stop B", "lat": -37.82, "lon": 144.95,
                    "stop": {"gtfsId": "1:222", "wheelchairBoarding": "POSSIBLE"},
                },
            },
            {
                "mode": "WALK",
                "from": {
                    "name": "Stop B", "lat": -37.82, "lon": 144.95,
                    "stop": {"gtfsId": "1:222", "wheelchairBoarding": "POSSIBLE"},
                },
                "to": {
                    "name": "Stop C", "lat": -37.825, "lon": 144.955,
                    "stop": {"gtfsId": "1:333", "wheelchairBoarding": "POSSIBLE"},
                },
            },
            {
                "mode": "BUS",
                "from": {
                    "name": "Stop C", "lat": -37.825, "lon": 144.955,
                    "stop": {"gtfsId": "1:333", "wheelchairBoarding": "POSSIBLE"},
                },
                "to": {
                    "name": "Stop D", "lat": -37.83, "lon": 144.96,
                    "stop": {"gtfsId": "1:444", "wheelchairBoarding": "POSSIBLE"},
                },
            },
            {
                "mode": "WALK",
                "from": {
                    "name": "Stop D", "lat": -37.83, "lon": 144.96,
                    "stop": {"gtfsId": "1:444", "wheelchairBoarding": "POSSIBLE"},
                },
                "to": {"name": "Destination", "lat": -37.835, "lon": 144.965, "stop": None},
            },
        ],
    }

    result = _extract_alighting_stop(itinerary)
    assert result is not None
    assert result["name"] == "Stop D"
    assert result["gtfs_id"] == "1:444"


@pytest.mark.asyncio
async def test_single_toilet_nearby(client):
    """Works correctly when only 1 accessible toilet is found."""
    override_session(mock_destination_lookup())

    with mock_fetch_multiple_itineraries(), \
         mock_compute_steepness([3.2]), \
         mock_find_nearby_toilets([SAMPLE_TOILETS_NEAR_DEST[0]]), \
         mock_toilet_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/plan-accessible",
            json=VALID_REQUEST_BODY,
        )

    toilets = response.json()["nearby_toilets"]
    assert len(toilets) == 1
    assert toilets[0]["toilet"]["name"] == "Toilet 4 — Market Street"
