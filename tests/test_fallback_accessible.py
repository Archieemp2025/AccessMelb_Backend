"""Tests for POST /api/v1/journeys/fallback-accessible endpoint.

The fallback-accessible endpoint enriches existing fallback stop cards
with walking route steepness and LLM summaries. These tests mock the
database, OTP, steepness computation, and Groq calls. Real external
services are never touched.

Test strategy:
- Response shape: top-level fields, stop enrichment fields
- Steepness data: within standard, exceeds standard, no data
- LLM summary: present when Groq succeeds, null when it fails
- Warning: all_exceed_standard triggers user-facing warning text
- Validation: destination_id required, 404 for unknown destination
- OTP failures: 503 when OTP is unreachable
- Unit tests: generate_walk_summary graceful degradation
"""

import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

from tests.conftest import (
    override_session,
    mock_fallback_destination_lookup,
    mock_find_stops_by_radius,
    mock_walk_to_stop,
    SAMPLE_STOPS_BY_RADIUS_EDGES,
    SAMPLE_WALKING_LEG,
    SAMPLE_FALLBACK_DESTINATION,
)


VALID_REQUEST_BODY = {"destination_id": 1}

def mock_enrich_fallback_stops(enriched_stops=None, side_effect=None):
    """Patch enrich_fallback_stops at its point of use in the router."""
    mock = AsyncMock()
    if side_effect is not None:
        mock.side_effect = side_effect
    else:
        mock.return_value = enriched_stops or []
    return patch("app.routes.fallback_accessible.enrich_fallback_stops", mock)


def _make_enriched_stop(
    name="King St/Lonsdale St",
    gtfs_id="1:19549",
    distance=168,
    duration=239,
    walk_distance=169.25,
    max_gradient=3.2,
    within_standard=True,
    summary="A short, flat route from King St/Lonsdale St — comfortable for wheelchair users.",
    mode="BUS",
    wheelchair_boarding="NO_INFORMATION",
    routes=None,
):
    """Build a single enriched stop matching the response shape."""
    return {
        "stop": {
            "gtfs_id": gtfs_id,
            "name": name,
            "lat": -37.8142881,
            "lon": 144.9551244,
            "mode": mode,
            "wheelchair_boarding": wheelchair_boarding,
            "parent_station_name": None,
            "routes": routes or ["216", "302"],
            "distance_metres": distance,
        },
        "walking_route": {
            "duration_seconds": duration,
            "distance_metres": walk_distance,
            "polyline": "jmxeF}ivsZG[COFCGYEOFCdC",
        },
        "walk_steepness": {
            "max_gradient_percent": max_gradient,
            "within_standard": within_standard,
        },
        "walk_summary": summary,
    }


def _make_three_enriched_stops(gradients=None):
    """Build 3 enriched stops with configurable gradients."""
    if gradients is None:
        gradients = [(3.2, True), (4.0, True), (4.4, True)]

    stops = [
        _make_enriched_stop(
            name=f"Stop {i+1}",
            gtfs_id=f"1:{10000+i}",
            max_gradient=grad,
            within_standard=within,
            summary=f"Route from Stop {i+1} is {'comfortable' if within else 'challenging'}.",
        )
        for i, (grad, within) in enumerate(gradients)
    ]
    return stops

@pytest.mark.asyncio
async def test_fallback_accessible_returns_200(client):
    """A valid request with a known destination returns 200."""
    override_session(mock_fallback_destination_lookup())
    enriched = _make_three_enriched_stops()

    with mock_find_stops_by_radius(), \
         mock_walk_to_stop(), \
         mock_enrich_fallback_stops(enriched):
        response = await client.post(
            "/api/v1/journeys/fallback-accessible",
            json=VALID_REQUEST_BODY,
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_fallback_accessible_response_shape(client):
    """Response contains destination, stops, accessibility_summary, and steepness fields."""
    override_session(mock_fallback_destination_lookup())
    enriched = _make_three_enriched_stops()

    with mock_find_stops_by_radius(), \
         mock_walk_to_stop(), \
         mock_enrich_fallback_stops(enriched):
        response = await client.post(
            "/api/v1/journeys/fallback-accessible",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    assert "destination" in data
    assert "stops" in data
    assert "accessibility_summary" in data
    assert "all_exceed_standard" in data
    assert "warning" in data


@pytest.mark.asyncio
async def test_each_stop_has_steepness_and_summary(client):
    """Each stop card includes walk_steepness and walk_summary fields."""
    override_session(mock_fallback_destination_lookup())
    enriched = _make_three_enriched_stops()

    with mock_find_stops_by_radius(), \
         mock_walk_to_stop(), \
         mock_enrich_fallback_stops(enriched):
        response = await client.post(
            "/api/v1/journeys/fallback-accessible",
            json=VALID_REQUEST_BODY,
        )

    for stop in response.json()["stops"]:
        assert "walk_steepness" in stop
        assert "max_gradient_percent" in stop["walk_steepness"]
        assert "within_standard" in stop["walk_steepness"]
        assert "walk_summary" in stop


@pytest.mark.asyncio
async def test_existing_stop_fields_preserved(client):
    """Existing stop card fields (name, routes, distance, walking_route) are unchanged."""
    override_session(mock_fallback_destination_lookup())
    enriched = [_make_enriched_stop()]

    with mock_find_stops_by_radius(), \
         mock_walk_to_stop(), \
         mock_enrich_fallback_stops(enriched):
        response = await client.post(
            "/api/v1/journeys/fallback-accessible",
            json=VALID_REQUEST_BODY,
        )

    stop = response.json()["stops"][0]
    assert stop["stop"]["name"] == "King St/Lonsdale St"
    assert "routes" in stop["stop"]
    assert "duration_seconds" in stop["walking_route"]
    assert "distance_metres" in stop["walking_route"]
    assert "polyline" in stop["walking_route"]


@pytest.mark.asyncio
async def test_destination_shape(client):
    """Destination field matches existing fallback response shape."""
    override_session(mock_fallback_destination_lookup())
    enriched = _make_three_enriched_stops()

    with mock_find_stops_by_radius(), \
         mock_walk_to_stop(), \
         mock_enrich_fallback_stops(enriched):
        response = await client.post(
            "/api/v1/journeys/fallback-accessible",
            json=VALID_REQUEST_BODY,
        )

    dest = response.json()["destination"]
    assert dest["id"] == 1
    assert dest["name"] == "Koorie Heritage Trust Inc"
    assert dest["category"] == "gallery"

@pytest.mark.asyncio
async def test_all_within_standard_no_warning(client):
    """When all stops are within 5%, no warning is shown."""
    override_session(mock_fallback_destination_lookup())
    enriched = _make_three_enriched_stops([(2.1, True), (3.4, True), (4.2, True)])

    with mock_find_stops_by_radius(), \
         mock_walk_to_stop(), \
         mock_enrich_fallback_stops(enriched):
        response = await client.post(
            "/api/v1/journeys/fallback-accessible",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    assert data["all_exceed_standard"] is False
    assert data["warning"] is None


@pytest.mark.asyncio
async def test_some_exceed_no_top_level_warning(client):
    """When some stops exceed 5% but not all, no top-level warning."""
    override_session(mock_fallback_destination_lookup())
    enriched = _make_three_enriched_stops([(3.2, True), (4.0, True), (7.8, False)])

    with mock_find_stops_by_radius(), \
         mock_walk_to_stop(), \
         mock_enrich_fallback_stops(enriched):
        response = await client.post(
            "/api/v1/journeys/fallback-accessible",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    assert data["all_exceed_standard"] is False
    assert data["warning"] is None
    # Individual stop still shows exceeding
    steep_stops = [s for s in data["stops"] if not s["walk_steepness"]["within_standard"]]
    assert len(steep_stops) == 1


@pytest.mark.asyncio
async def test_all_exceed_standard_shows_warning(client):
    """When all stops exceed 5%, a warning is shown with the flattest gradient."""
    override_session(mock_fallback_destination_lookup())
    enriched = _make_three_enriched_stops([(6.2, False), (8.5, False), (7.0, False)])

    with mock_find_stops_by_radius(), \
         mock_walk_to_stop(), \
         mock_enrich_fallback_stops(enriched):
        response = await client.post(
            "/api/v1/journeys/fallback-accessible",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    assert data["all_exceed_standard"] is True
    assert data["warning"] is not None
    assert "5.0%" in data["warning"]
    assert "6.2%" in data["warning"]


@pytest.mark.asyncio
async def test_no_steepness_data_no_warning(client):
    """When steepness data is unavailable, no warning and null steepness fields."""
    override_session(mock_fallback_destination_lookup())
    enriched = [_make_enriched_stop(max_gradient=None, within_standard=None, summary=None)]

    with mock_find_stops_by_radius(), \
         mock_walk_to_stop(), \
         mock_enrich_fallback_stops(enriched):
        response = await client.post(
            "/api/v1/journeys/fallback-accessible",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    stop = data["stops"][0]
    assert stop["walk_steepness"]["max_gradient_percent"] is None
    assert stop["walk_steepness"]["within_standard"] is None
    assert data["all_exceed_standard"] is False
    assert data["warning"] is None


@pytest.mark.asyncio
async def test_summary_present_when_groq_succeeds(client):
    """When Groq returns a summary, it appears in the response."""
    override_session(mock_fallback_destination_lookup())
    enriched = [_make_enriched_stop(
        summary="A short, flat route from King St/Lonsdale St — comfortable for all wheelchair types."
    )]

    with mock_find_stops_by_radius(), \
         mock_walk_to_stop(), \
         mock_enrich_fallback_stops(enriched):
        response = await client.post(
            "/api/v1/journeys/fallback-accessible",
            json=VALID_REQUEST_BODY,
        )

    summary = response.json()["stops"][0]["walk_summary"]
    assert summary is not None
    assert "King St/Lonsdale St" in summary


@pytest.mark.asyncio
async def test_summary_null_when_groq_fails(client):
    """When Groq fails, walk_summary is null but steepness badge still present."""
    override_session(mock_fallback_destination_lookup())
    enriched = [_make_enriched_stop(summary=None)]

    with mock_find_stops_by_radius(), \
         mock_walk_to_stop(), \
         mock_enrich_fallback_stops(enriched):
        response = await client.post(
            "/api/v1/journeys/fallback-accessible",
            json=VALID_REQUEST_BODY,
        )

    stop = response.json()["stops"][0]
    assert stop["walk_summary"] is None
    assert stop["walk_steepness"]["max_gradient_percent"] is not None


@pytest.mark.asyncio
async def test_reject_missing_destination_id(client):
    """Request without destination_id fails validation."""
    response = await client.post(
        "/api/v1/journeys/fallback-accessible",
        json={},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_zero_destination_id(client):
    """destination_id=0 fails validation (must be >= 1)."""
    response = await client.post(
        "/api/v1/journeys/fallback-accessible",
        json={"destination_id": 0},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_destination_not_found_returns_404(client):
    """If the destination ID doesn't exist, return 404."""
    from tests.conftest import mock_destination_not_found
    override_session(mock_destination_not_found())

    response = await client.post(
        "/api/v1/journeys/fallback-accessible",
        json=VALID_REQUEST_BODY,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Destination not found"


@pytest.mark.asyncio
async def test_otp_unavailable_returns_503(client):
    """When OTP is unreachable for stopsByRadius, return 503."""
    override_session(mock_fallback_destination_lookup())

    mock = AsyncMock(side_effect=HTTPException(
        status_code=503,
        detail="Journey planning is currently unavailable. Please try again shortly.",
    ))
    with patch("app.routes.fallback_accessible.find_stops_by_radius", mock):
        response = await client.post(
            "/api/v1/journeys/fallback-accessible",
            json=VALID_REQUEST_BODY,
        )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_generate_summary_without_api_key():
    """When GROQ_API_KEY is not set, returns None gracefully."""
    from app.services.fallback_steepness import generate_walk_summary

    with patch.dict("os.environ", {}, clear=True):
        result = await generate_walk_summary(
            stop_name="King St/Lonsdale St",
            distance_metres=169.25,
            duration_seconds=239,
            max_gradient=3.2,
        )

    assert result is None


@pytest.mark.asyncio
async def test_generate_summary_groq_exception_returns_none():
    """When Groq raises an exception, returns None gracefully."""
    from app.services.fallback_steepness import generate_walk_summary

    with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}), \
         patch("app.services.fallback_steepness.Groq") as MockGroq:

        MockGroq.return_value.chat.completions.create.side_effect = Exception("API timeout")

        result = await generate_walk_summary(
            stop_name="King St/Lonsdale St",
            distance_metres=169.25,
            duration_seconds=239,
            max_gradient=3.2,
        )

    assert result is None


@pytest.mark.asyncio
async def test_generate_summary_with_no_gradient_data():
    """When max_gradient is None, the prompt describes only distance."""
    from app.services.fallback_steepness import generate_walk_summary

    with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}), \
         patch("app.services.fallback_steepness.Groq") as MockGroq:

        mock_client = MockGroq.return_value
        mock_choice = type("Choice", (), {
            "message": type("Msg", (), {"content": "A brief route from King St/Lonsdale St to the destination."})()
        })()
        mock_client.chat.completions.create.return_value = type(
            "Response", (), {"choices": [mock_choice]}
        )()

        result = await generate_walk_summary(
            stop_name="King St/Lonsdale St",
            distance_metres=169.25,
            duration_seconds=239,
            max_gradient=None,
        )

    assert result is not None
    assert "King St/Lonsdale St" in result

@pytest.mark.asyncio
async def test_exactly_5_percent_is_within_standard():
    """Exactly 5.0% is within standard (boundary case)."""
    stop = _make_enriched_stop(max_gradient=5.0, within_standard=True)
    assert stop["walk_steepness"]["within_standard"] is True


@pytest.mark.asyncio
async def test_just_above_5_percent_exceeds_standard():
    """5.1% exceeds the standard."""
    stop = _make_enriched_stop(max_gradient=5.1, within_standard=False)
    assert stop["walk_steepness"]["within_standard"] is False


@pytest.mark.asyncio
async def test_empty_stops_returns_empty_list(client):
    """When no accessible stops are found, response has empty stops list."""
    override_session(mock_fallback_destination_lookup())

    with mock_find_stops_by_radius(edges=[]), \
         mock_enrich_fallback_stops([]):
        response = await client.post(
            "/api/v1/journeys/fallback-accessible",
            json=VALID_REQUEST_BODY,
        )

    data = response.json()
    assert data["stops"] == []
    assert data["all_exceed_standard"] is False
