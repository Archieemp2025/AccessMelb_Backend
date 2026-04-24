"""Tests for POST /api/v1/journeys/fallback endpoint.

The fallback endpoint is used when the user declines browser geolocation.
It returns up to 3 nearby accessible stops with walking routes to the
destination. These tests mock both the database and OTP, no real services
are touched.

Test strategy:
- Correct path: response shape, all expected fields present
- Stop filtering: NOT_POSSIBLE excluded, duplicates removed, NO_INFORMATION kept
- Route sorting: numeric routes in ascending order, non-numeric last
- Validation: destination_id required, must be positive integer
- Database failures: 404 when destination not found
- OTP failures: 503 on transport errors, skipped stops when no walking route
- Radius expansion: second query runs when first returns insufficient stops
- Warnings: INSUFFICIENT_STOPS, UNKNOWN_STOP_ACCESSIBILITY, LONG_WALK
"""

import pytest
from fastapi import HTTPException

from tests.conftest import (
    override_session,
    create_mock_session,
    mock_fallback_destination_lookup,
    mock_destination_not_found,
    mock_find_stops_by_radius,
    mock_walk_to_stop,
    SAMPLE_STOPS_BY_RADIUS_EDGES,
    SAMPLE_WALKING_LEG,
)


VALID_REQUEST_BODY = {"destination_id": 1}


@pytest.mark.asyncio
async def test_fallback_returns_200(client):
    """A valid destination ID returns 200 with a complete response."""
    override_session(mock_fallback_destination_lookup())

    with mock_find_stops_by_radius(), mock_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/fallback",
            json=VALID_REQUEST_BODY,
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_fallback_response_shape(client):
    """Response contains destination, stops, and accessibility_summary."""
    override_session(mock_fallback_destination_lookup())

    with mock_find_stops_by_radius(), mock_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/fallback",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    assert "destination" in data
    assert "stops" in data
    assert "accessibility_summary" in data


@pytest.mark.asyncio
async def test_fallback_destination_includes_name_and_category(client):
    """Destination block includes all expected fields for the frontend."""
    override_session(mock_fallback_destination_lookup())

    with mock_find_stops_by_radius(), mock_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/fallback",
            json=VALID_REQUEST_BODY,
        )

    destination = response.json()["destination"]
    assert destination["id"] == 1
    assert destination["name"] == "Koorie Heritage Trust Inc"
    assert destination["category"] == "gallery"
    assert "lat" in destination
    assert "lon" in destination


@pytest.mark.asyncio
async def test_fallback_returns_three_stops(client):
    """When 3+ accessible stops are nearby, return exactly 3."""
    override_session(mock_fallback_destination_lookup())

    with mock_find_stops_by_radius(), mock_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/fallback",
            json=VALID_REQUEST_BODY,
        )

    assert len(response.json()["stops"]) == 3


@pytest.mark.asyncio
async def test_fallback_stop_shape(client):
    """Each stop has all the fields the frontend needs."""
    override_session(mock_fallback_destination_lookup())

    with mock_find_stops_by_radius(), mock_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/fallback",
            json=VALID_REQUEST_BODY,
        )

    first = response.json()["stops"][0]
    for field in ["stop", "walking_route"]:
        assert field in first

    stop = first["stop"]
    for field in [
        "gtfs_id", "name", "lat", "lon", "mode", "wheelchair_boarding",
        "parent_station_name", "routes", "distance_metres",
    ]:
        assert field in stop, f"Missing field: {field}"

    route = first["walking_route"]
    for field in ["duration_seconds", "distance_metres", "polyline"]:
        assert field in route, f"Missing field: {field}"

@pytest.mark.asyncio
async def test_fallback_rejects_missing_destination_id(client):
    """Request without destination_id fails schema validation."""
    response = await client.post(
        "/api/v1/journeys/fallback",
        json={},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_fallback_rejects_zero_destination_id(client):
    """destination_id=0 fails validation (must be >= 1)."""
    response = await client.post(
        "/api/v1/journeys/fallback",
        json={"destination_id": 0},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_fallback_rejects_non_integer_destination_id(client):
    """Non-integer destination_id fails validation."""
    response = await client.post(
        "/api/v1/journeys/fallback",
        json={"destination_id": "abc"},
    )
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_fallback_destination_not_found_returns_404(client):
    """Unknown destination_id returns 404 before any OTP call happens."""
    override_session(mock_destination_not_found())

    response = await client.post(
        "/api/v1/journeys/fallback",
        json=VALID_REQUEST_BODY,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Destination not found"

@pytest.mark.asyncio
async def test_fallback_otp_unavailable_returns_503(client):
    """When the stops-by-radius OTP call fails, return 503."""
    override_session(mock_fallback_destination_lookup())

    with mock_find_stops_by_radius() as stops_mock:
        stops_mock.side_effect = HTTPException(
            status_code=503,
            detail="Journey planning is currently unavailable. Please try again shortly.",
        )

        response = await client.post(
            "/api/v1/journeys/fallback",
            json=VALID_REQUEST_BODY,
        )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_fallback_skips_stops_with_no_walking_route(client):
    """If a walking route lookup returns None, that stop is skipped from results."""
    override_session(mock_fallback_destination_lookup())

    # First two stops have walking routes, third returns None
    walking_side_effects = [SAMPLE_WALKING_LEG, SAMPLE_WALKING_LEG, None]

    with mock_find_stops_by_radius(), mock_walk_to_stop(side_effect=walking_side_effects):
        response = await client.post(
            "/api/v1/journeys/fallback",
            json=VALID_REQUEST_BODY,
        )

    # Only 2 stops should come back; third was skipped
    assert response.status_code == 200
    assert len(response.json()["stops"]) == 2

@pytest.mark.asyncio
async def test_filter_excludes_not_possible_stops():
    """NOT_POSSIBLE stops are filtered out; others pass through."""
    from app.services.otp.transformers import filter_accessible_stops

    edges = [
        {"node": {"stop": {
            "gtfsId": "1:1", "name": "Accessible", "wheelchairBoarding": "POSSIBLE",
            "lat": 0, "lon": 0,
        }, "distance": 100}},
        {"node": {"stop": {
            "gtfsId": "1:2", "name": "Not Accessible", "wheelchairBoarding": "NOT_POSSIBLE",
            "lat": 0, "lon": 0,
        }, "distance": 200}},
        {"node": {"stop": {
            "gtfsId": "1:3", "name": "Unknown", "wheelchairBoarding": "NO_INFORMATION",
            "lat": 0, "lon": 0,
        }, "distance": 300}},
    ]

    result = filter_accessible_stops(edges)
    assert len(result) == 2
    names = [e["node"]["stop"]["name"] for e in result]
    assert "Accessible" in names
    assert "Unknown" in names
    assert "Not Accessible" not in names


@pytest.mark.asyncio
async def test_filter_deduplicates_by_name():
    """Stops with identical names (inbound/outbound variants) are deduplicated."""
    from app.services.otp.transformers import filter_accessible_stops

    edges = [
        {"node": {"stop": {
            "gtfsId": "1:1", "name": "Same Stop", "wheelchairBoarding": "POSSIBLE",
            "lat": 0, "lon": 0,
        }, "distance": 100}},
        {"node": {"stop": {
            "gtfsId": "1:2", "name": "Same Stop", "wheelchairBoarding": "POSSIBLE",
            "lat": 0, "lon": 0,
        }, "distance": 120}},
        {"node": {"stop": {
            "gtfsId": "1:3", "name": "Different Stop", "wheelchairBoarding": "POSSIBLE",
            "lat": 0, "lon": 0,
        }, "distance": 200}},
    ]

    result = filter_accessible_stops(edges)
    assert len(result) == 2

    # The first occurrence is kept (closest by distance since OTP sorts by distance)
    names = [e["node"]["stop"]["name"] for e in result]
    assert names == ["Same Stop", "Different Stop"]

@pytest.mark.asyncio
async def test_routes_sorted_numerically():
    """Routes in each stop are sorted numerically ascending."""
    from app.services.otp.transformers import transform_fallback_stop

    edge = {
        "node": {
            "stop": {
                "gtfsId": "1:100",
                "name": "Test Stop",
                "lat": 0, "lon": 0,
                "vehicleMode": "BUS",
                "wheelchairBoarding": "POSSIBLE",
                "parentStation": None,
                "routes": [
                    {"shortName": "302"},
                    {"shortName": "86"},
                    {"shortName": "906"},
                    {"shortName": "216"},
                ],
            },
            "distance": 100,
        }
    }

    result = transform_fallback_stop(edge, SAMPLE_WALKING_LEG)
    assert result["stop"]["routes"] == ["86", "216", "302", "906"]


@pytest.mark.asyncio
async def test_routes_non_numeric_sorted_last():
    """Routes without numeric shortnames are sorted after numeric ones."""
    from app.services.otp.transformers import transform_fallback_stop

    edge = {
        "node": {
            "stop": {
                "gtfsId": "1:100",
                "name": "Test Stop",
                "lat": 0, "lon": 0,
                "vehicleMode": "BUS",
                "wheelchairBoarding": "POSSIBLE",
                "parentStation": None,
                "routes": [
                    {"shortName": "302"},
                    {"shortName": "Light Rail"},
                    {"shortName": "86"},
                ],
            },
            "distance": 100,
        }
    }

    result = transform_fallback_stop(edge, SAMPLE_WALKING_LEG)
    assert result["stop"]["routes"] == ["86", "302", "Light Rail"]

@pytest.mark.asyncio
async def test_radius_expands_when_fewer_than_three_stops(client):
    """When the initial radius returns fewer than 3 stops, the larger radius is queried."""
    override_session(mock_fallback_destination_lookup())

    # First call (500m) returns only 1 stop; second call (800m) returns 3
    one_stop = SAMPLE_STOPS_BY_RADIUS_EDGES[:1]
    three_stops = SAMPLE_STOPS_BY_RADIUS_EDGES

    with mock_find_stops_by_radius() as stops_mock, mock_walk_to_stop():
        stops_mock.side_effect = [one_stop, three_stops]

        response = await client.post(
            "/api/v1/journeys/fallback",
            json=VALID_REQUEST_BODY,
        )

        # Both radius searches should have been called
        assert stops_mock.call_count == 2

    assert response.status_code == 200
    assert len(response.json()["stops"]) == 3


@pytest.mark.asyncio
async def test_radius_not_expanded_when_three_stops_found(client):
    """When the initial radius returns 3+ stops, the expanded search is skipped."""
    override_session(mock_fallback_destination_lookup())

    with mock_find_stops_by_radius() as stops_mock, mock_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/fallback",
            json=VALID_REQUEST_BODY,
        )

        # Only the initial radius query happened
        assert stops_mock.call_count == 1

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_insufficient_stops_warning(client):
    """A warning is raised when fewer than 3 stops are returned."""
    override_session(mock_fallback_destination_lookup())

    # Only 1 stop available, even after expansion
    with mock_find_stops_by_radius(edges=SAMPLE_STOPS_BY_RADIUS_EDGES[:1]), mock_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/fallback",
            json=VALID_REQUEST_BODY,
        )

    warnings = response.json()["accessibility_summary"]["warnings"]
    insufficient = [w for w in warnings if w["type"] == "INSUFFICIENT_STOPS"]
    assert len(insufficient) == 1


@pytest.mark.asyncio
async def test_unknown_accessibility_warning_per_stop(client):
    """NO_INFORMATION stops each generate an UNKNOWN_STOP_ACCESSIBILITY warning."""
    override_session(mock_fallback_destination_lookup())

    with mock_find_stops_by_radius(), mock_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/fallback",
            json=VALID_REQUEST_BODY,
        )

    warnings = response.json()["accessibility_summary"]["warnings"]
    unknown = [w for w in warnings if w["type"] == "UNKNOWN_STOP_ACCESSIBILITY"]
    # All 3 sample stops are NO_INFORMATION
    assert len(unknown) == 3


@pytest.mark.asyncio
async def test_long_walk_warning():
    """Walking routes over 500m generate a LONG_WALK warning."""
    from app.services.otp.transformers import build_fallback_accessibility_summary

    stops = [
        {
            "stop": {"name": "Nearby Stop", "wheelchair_boarding": "POSSIBLE"},
            "walking_route": {"distance_metres": 600.0, "duration_seconds": 600},
        },
    ]

    summary = build_fallback_accessibility_summary(stops)
    long_walks = [w for w in summary["warnings"] if w["type"] == "LONG_WALK"]
    assert len(long_walks) == 1
    assert long_walks[0]["stop_index"] == 0


@pytest.mark.asyncio
async def test_fully_accessible_when_no_warnings():
    """fully_accessible is True only when no stop-level warnings exist."""
    from app.services.otp.transformers import build_fallback_accessibility_summary

    stops = [
        {
            "stop": {"name": "Clean Stop", "wheelchair_boarding": "POSSIBLE"},
            "walking_route": {"distance_metres": 200.0, "duration_seconds": 200},
        },
        {
            "stop": {"name": "Another Clean Stop", "wheelchair_boarding": "POSSIBLE"},
            "walking_route": {"distance_metres": 300.0, "duration_seconds": 300},
        },
        {
            "stop": {"name": "Third Clean Stop", "wheelchair_boarding": "POSSIBLE"},
            "walking_route": {"distance_metres": 250.0, "duration_seconds": 250},
        },
    ]

    summary = build_fallback_accessibility_summary(stops)
    assert summary["fully_accessible"] is True
    assert summary["warnings"] == []


@pytest.mark.asyncio
async def test_accessibility_summary_reflects_real_response(client):
    """End-to-end: the accessibility_summary structure is present and correct."""
    override_session(mock_fallback_destination_lookup())

    with mock_find_stops_by_radius(), mock_walk_to_stop():
        response = await client.post(
            "/api/v1/journeys/fallback",
            json=VALID_REQUEST_BODY,
        )

    summary = response.json()["accessibility_summary"]
    assert "fully_accessible" in summary
    assert "warnings" in summary
    assert isinstance(summary["warnings"], list)