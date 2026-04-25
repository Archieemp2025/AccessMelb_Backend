"""Tests for /api/v1/journeys/plan endpoint.

These tests mock both the database (for destination lookups) and OTP
(for routing). Real OTP and real database connections are never touched.

Test strategy:
- Correct path: verify response shape matches the schema
- Validation: verify Pydantic rejects bad input before reaching business logic
- Destination lookup: 404 when destination doesn't exist
- OTP failures: 404 for no-journey-found, 503 for transport errors
- Enrichments: wait_before_seconds, is_rail_replacement, accessibility_summary
"""

import pytest, json
from fastapi import HTTPException

from tests.conftest import (
    override_session,
    mock_plan_journey,
    mock_destination_lookup,
    mock_destination_not_found,
    SAMPLE_OTP_ITINERARY,
)


VALID_REQUEST_BODY = {
    "origin": {"lat": -37.8008, "lon": 144.9033},
    "destination_id": 1,
}


@pytest.mark.asyncio
async def test_plan_journey_returns_200(client):
    """A valid request with a known destination returns 200 and a journey."""
    override_session(mock_destination_lookup())

    with mock_plan_journey():
        response = await client.post(
            "/api/v1/journeys/plan",
            json=VALID_REQUEST_BODY,
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_plan_journey_response_shape(client):
    """Response contains all the top-level fields the frontend expects."""
    override_session(mock_destination_lookup())

    with mock_plan_journey():
        response = await client.post(
            "/api/v1/journeys/plan",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    assert "duration_seconds" in data
    assert "walk_distance_metres" in data
    assert "start_time" in data
    assert "end_time" in data
    assert "transfers" in data
    assert "legs" in data
    assert "accessibility_summary" in data


@pytest.mark.asyncio
async def test_plan_journey_leg_shape(client):
    """Each leg contains the fields the frontend needs to render a journey card."""
    override_session(mock_destination_lookup())

    with mock_plan_journey():
        response = await client.post(
            "/api/v1/journeys/plan",
            json=VALID_REQUEST_BODY,
        )

    leg = response.json()["legs"][0]
    for field in [
        "mode", "start_time", "end_time", "duration_seconds", "distance_metres",
        "from_stop", "to_stop", "polyline",
        "wait_before_seconds", "is_rail_replacement",
    ]:
        assert field in leg, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_plan_journey_transit_leg_has_route_info(client):
    """Transit legs include route name, headsign, and agency."""
    override_session(mock_destination_lookup())

    with mock_plan_journey():
        response = await client.post(
            "/api/v1/journeys/plan",
            json=VALID_REQUEST_BODY,
        )

    transit_legs = [leg for leg in response.json()["legs"] if leg["mode"] != "WALK"]
    assert len(transit_legs) > 0

    leg = transit_legs[0]
    assert leg["route_short_name"] == "Williamstown"
    assert leg["trip_headsign"] == "Flinders Street"
    assert leg["agency_name"] == "Transport Victoria"


@pytest.mark.asyncio
async def test_plan_journey_transfers_count(client):
    """Transfer count equals (transit legs - 1)."""
    override_session(mock_destination_lookup())

    with mock_plan_journey():
        response = await client.post(
            "/api/v1/journeys/plan",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    transit_legs = [leg for leg in data["legs"] if leg["mode"] != "WALK"]
    expected_transfers = max(0, len(transit_legs) - 1)
    assert data["transfers"] == expected_transfers


@pytest.mark.asyncio
async def test_reject_origin_outside_melbourne_bounds(client):
    """Coordinates outside Greater Melbourne are rejected at the schema layer."""
    response = await client.post(
        "/api/v1/journeys/plan",
        json={"origin": {"lat": 51.5074, "lon": -0.1278}, "destination_id": 1},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_missing_origin(client):
    """Request without origin fails validation."""
    response = await client.post(
        "/api/v1/journeys/plan",
        json={"destination_id": 1},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_missing_destination_id(client):
    """Request without destination_id fails validation."""
    response = await client.post(
        "/api/v1/journeys/plan",
        json={"origin": {"lat": -37.8008, "lon": 144.9033}},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_zero_destination_id(client):
    """destination_id=0 fails validation (must be >= 1)."""
    response = await client.post(
        "/api/v1/journeys/plan",
        json={"origin": {"lat": -37.8008, "lon": 144.9033}, "destination_id": 0},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_non_numeric_coordinates(client):
    """Non-numeric coordinate values are rejected."""
    response = await client.post(
        "/api/v1/journeys/plan",
        json={"origin": {"lat": "not-a-number", "lon": 144.9033}, "destination_id": 1},
    )
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_destination_not_found_returns_404(client):
    """If the destination ID doesn't exist in the database, return 404."""
    override_session(mock_destination_not_found())

    response = await client.post(
        "/api/v1/journeys/plan",
        json=VALID_REQUEST_BODY,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Destination not found"


@pytest.mark.asyncio
async def test_otp_no_journey_found_returns_404(client):
    """When OTP can't find an accessible journey, return 404."""
    override_session(mock_destination_lookup())

    with mock_plan_journey(side_effect=HTTPException(
        status_code=404,
        detail="No accessible journey found for this route and time. "
               "Services may not be running, or accessibility constraints "
               "may prevent a valid route.",
    )):
        response = await client.post(
            "/api/v1/journeys/plan",
            json=VALID_REQUEST_BODY,
        )

    assert response.status_code == 404
    assert "No accessible journey" in response.json()["detail"]


@pytest.mark.asyncio
async def test_otp_unavailable_returns_503(client):
    """When OTP is unreachable, return 503 with a generic message."""
    override_session(mock_destination_lookup())

    with mock_plan_journey(side_effect=HTTPException(
        status_code=503,
        detail="Journey planning is currently unavailable. Please try again shortly.",
    )):
        response = await client.post(
            "/api/v1/journeys/plan",
            json=VALID_REQUEST_BODY,
        )

    assert response.status_code == 503
    assert response.json()["detail"].startswith("Journey planning is currently unavailable")

@pytest.mark.asyncio
async def test_walking_leg_has_no_wait_before(client):
    """The first walking leg never has a wait_before_seconds value."""
    override_session(mock_destination_lookup())

    with mock_plan_journey():
        response = await client.post(
            "/api/v1/journeys/plan",
            json=VALID_REQUEST_BODY,
        )

    first_leg = response.json()["legs"][0]
    assert first_leg["wait_before_seconds"] is None


@pytest.mark.asyncio
async def test_rail_replacement_detection():
    """Rail replacement buses are detected from the route name."""
    # Import the transformer directly — this is a pure unit test of the
    # enrichment logic, no HTTP layer involved.
    from app.services.otp.transformers import _transform_leg

    leg_data = {
        "mode": "RAIL",
        "startTime": 0,
        "endTime": 60000,
        "duration": 60,
        "distance": 500.0,
        "from": {"name": "A", "lat": 0, "lon": 0},
        "to": {"name": "B", "lat": 0, "lon": 0},
        "route": {
            "shortName": "Replacement Bus",
            "longName": "Rail Replacement",
            "agency": {"name": "Vic"},
            "mode": "BUS",
        },
        "trip": {"tripHeadsign": "B", "wheelchairAccessible": "POSSIBLE"},
        "intermediateStops": [],
        "legGeometry": {"points": ""},
    }

    leg = _transform_leg(leg_data)
    assert leg["is_rail_replacement"] is True


@pytest.mark.asyncio
async def test_regular_train_is_not_rail_replacement():
    """Regular train services are not flagged as rail replacement."""
    from app.services.otp.transformers import _transform_leg

    leg_data = {
        "mode": "RAIL",
        "startTime": 0,
        "endTime": 60000,
        "duration": 60,
        "distance": 500.0,
        "from": {"name": "A", "lat": 0, "lon": 0},
        "to": {"name": "B", "lat": 0, "lon": 0},
        "route": {
            "shortName": "Werribee",
            "longName": "Werribee - City",
            "agency": {"name": "Transport Victoria"},
            "mode": "RAIL",
        },
        "trip": {"tripHeadsign": "Flinders Street", "wheelchairAccessible": "POSSIBLE"},
        "intermediateStops": [],
        "legGeometry": {"points": ""},
    }

    leg = _transform_leg(leg_data)
    assert leg["is_rail_replacement"] is False


@pytest.mark.asyncio
async def test_long_walk_triggers_warning():
    """A walking leg over 500m produces a LONG_WALK warning."""
    from app.services.otp.transformers import _compute_accessibility_summary

    legs = [{
        "mode": "WALK",
        "distance_metres": 600.0,
        "is_rail_replacement": False,
        "trip_wheelchair_accessible": None,
        "wait_before_seconds": None,
    }]

    summary = _compute_accessibility_summary(legs)
    assert summary["fully_accessible"] is False
    assert len(summary["warnings"]) == 1
    assert summary["warnings"][0]["type"] == "LONG_WALK"
    assert summary["warnings"][0]["leg_index"] == 0


@pytest.mark.asyncio
async def test_short_walk_no_warning():
    """A walking leg under 500m produces no warning."""
    from app.services.otp.transformers import _compute_accessibility_summary

    legs = [{
        "mode": "WALK",
        "distance_metres": 300.0,
        "is_rail_replacement": False,
        "trip_wheelchair_accessible": None,
        "wait_before_seconds": None,
    }]

    summary = _compute_accessibility_summary(legs)
    assert summary["fully_accessible"] is True
    assert summary["warnings"] == []


@pytest.mark.asyncio
async def test_long_wait_triggers_warning():
    """A transit leg with a wait over 20 minutes produces a LONG_WAIT warning."""
    from app.services.otp.transformers import _compute_accessibility_summary

    legs = [
        {
            "mode": "RAIL",
            "distance_metres": 1000.0,
            "is_rail_replacement": False,
            "trip_wheelchair_accessible": "POSSIBLE",
            "wait_before_seconds": None,
        },
        {
            "mode": "RAIL",
            "distance_metres": 1000.0,
            "is_rail_replacement": False,
            "trip_wheelchair_accessible": "POSSIBLE",
            "wait_before_seconds": 1500,   # 25 minutes
        },
    ]

    summary = _compute_accessibility_summary(legs)
    warnings = [w for w in summary["warnings"] if w["type"] == "LONG_WAIT"]
    assert len(warnings) == 1
    assert warnings[0]["leg_index"] == 1


@pytest.mark.asyncio
async def test_unknown_accessibility_triggers_warning():
    """Trip with NO_INFORMATION accessibility produces a warning."""
    from app.services.otp.transformers import _compute_accessibility_summary

    legs = [{
        "mode": "TRAM",
        "distance_metres": 500.0,
        "is_rail_replacement": False,
        "trip_wheelchair_accessible": "NO_INFORMATION",
        "wait_before_seconds": None,
    }]

    summary = _compute_accessibility_summary(legs)
    warnings = [w for w in summary["warnings"] if w["type"] == "UNKNOWN_ACCESSIBILITY"]
    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_fully_accessible_journey_has_no_warnings():
    """A clean journey with short walks and accessible transit produces no warnings."""
    from app.services.otp.transformers import _compute_accessibility_summary

    legs = [
        {
            "mode": "WALK",
            "distance_metres": 200.0,
            "is_rail_replacement": False,
            "trip_wheelchair_accessible": None,
            "wait_before_seconds": None,
        },
        {
            "mode": "RAIL",
            "distance_metres": 5000.0,
            "is_rail_replacement": False,
            "trip_wheelchair_accessible": "POSSIBLE",
            "wait_before_seconds": None,
        },
        {
            "mode": "WALK",
            "distance_metres": 150.0,
            "is_rail_replacement": False,
            "trip_wheelchair_accessible": None,
            "wait_before_seconds": None,
        },
    ]

    summary = _compute_accessibility_summary(legs)
    assert summary["fully_accessible"] is True
    assert summary["warnings"] == []


@pytest.mark.asyncio
async def test_accessibility_summary_in_response(client):
    """The response includes the accessibility_summary field."""
    override_session(mock_destination_lookup())

    with mock_plan_journey():
        response = await client.post(
            "/api/v1/journeys/plan",
            json=VALID_REQUEST_BODY,
        )

    summary = response.json()["accessibility_summary"]
    assert "fully_accessible" in summary
    assert "warnings" in summary
    assert isinstance(summary["warnings"], list)