import pytest

from tests.conftest import (
    create_mock_session,
    override_session,
    mock_fetch_venue_details,
    SAMPLE_DESTINATIONS,
    SAMPLE_DETAIL_DESTINATIONS,
    SAMPLE_TOILETS,
    SAMPLE_DESTINATION_WITHOUT_PLACE_ID,
    SAMPLE_GOOGLE_PLACES_RESPONSE,
    DestinationRow,
)


# GET-destinations



@pytest.mark.asyncio
async def test_get_all_destinations(client):
    session = create_mock_session(
        scalar_value=3,
        execute_results=[SAMPLE_DESTINATIONS],
    )
    override_session(session)

    response = await client.get("/api/v1/destinations")

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 3
    assert data["limit"] == 20
    assert data["offset"] == 0
    assert len(data["destinations"]) == 3


@pytest.mark.asyncio
async def test_destination_response_structure(client):
    session = create_mock_session(
        scalar_value=1,
        execute_results=[SAMPLE_DESTINATIONS[:1]],
    )
    override_session(session)

    response = await client.get("/api/v1/destinations")
    destination = response.json()["destinations"][0]

    assert "destination_id" in destination
    assert "feature_name" in destination
    assert "category" in destination
    assert "sub_theme" in destination
    assert "latitude" in destination
    assert "longitude" in destination


@pytest.mark.asyncio
async def test_filter_by_category(client):
    galleries = [d for d in SAMPLE_DESTINATIONS if d.category == "gallery"]
    session = create_mock_session(
        scalar_value=len(galleries),
        execute_results=[galleries],
    )
    override_session(session)

    response = await client.get("/api/v1/destinations", params={"category": "gallery"})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert all(d["category"] == "gallery" for d in data["destinations"])


@pytest.mark.asyncio
async def test_search_by_name(client):
    matched = [d for d in SAMPLE_DESTINATIONS if "national" in d.feature_name.lower()]
    session = create_mock_session(
        scalar_value=len(matched),
        execute_results=[matched],
    )
    override_session(session)

    response = await client.get("/api/v1/destinations", params={"search": "national"})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert "National" in data["destinations"][0]["feature_name"]


@pytest.mark.asyncio
async def test_pagination(client):
    session = create_mock_session(
        scalar_value=3,
        execute_results=[SAMPLE_DESTINATIONS[1:2]],
    )
    override_session(session)

    response = await client.get("/api/v1/destinations", params={"limit": 1, "offset": 1})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 3
    assert data["limit"] == 1
    assert data["offset"] == 1
    assert len(data["destinations"]) == 1


@pytest.mark.asyncio
async def test_empty_results(client):
    session = create_mock_session(
        scalar_value=0,
        execute_results=[[]],
    )
    override_session(session)

    response = await client.get("/api/v1/destinations", params={"search": "nonexistent"})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
    assert data["destinations"] == []


@pytest.mark.asyncio
async def test_invalid_limit_too_high(client):
    response = await client.get("/api/v1/destinations", params={"limit": 200})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_limit_too_low(client):
    response = await client.get("/api/v1/destinations", params={"limit": 0})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_offset_negative(client):
    response = await client.get("/api/v1/destinations", params={"offset": -1})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_combined_filters(client):
    session = create_mock_session(
        scalar_value=1,
        execute_results=[[SAMPLE_DESTINATIONS[0]]],
    )
    override_session(session)

    response = await client.get(
        "/api/v1/destinations",
        params={"category": "gallery", "search": "national", "limit": 10, "offset": 0},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["destinations"][0]["category"] == "gallery"


# ── GET /destinations/{destination_id} ───────────────────────


@pytest.mark.asyncio
async def test_get_destination_with_nearby_toilets(client):
    session = create_mock_session(
        execute_results=[
            SAMPLE_DETAIL_DESTINATIONS,  # destination query
            SAMPLE_TOILETS,            # nearby toilets query
        ],
    )
    override_session(session)

    response = await client.get("/api/v1/destinations/1")

    assert response.status_code == 200
    data = response.json()

    assert data["destination"]["destination_id"] == 1
    assert data["destination"]["feature_name"] == "National Gallery of Victoria"

    assert data["nearby_toilets"]["radius_m"] == 500
    assert data["nearby_toilets"]["count"] == 2
    assert len(data["nearby_toilets"]["toilets"]) == 2


@pytest.mark.asyncio
async def test_destination_detail_response_structure(client):
    session = create_mock_session(
        execute_results=[
            SAMPLE_DETAIL_DESTINATIONS,
            SAMPLE_TOILETS[:1],
        ],
    )
    override_session(session)

    response = await client.get("/api/v1/destinations/1")
    data = response.json()

    destination = data["destination"]
    assert "destination_id" in destination
    assert "feature_name" in destination
    assert "category" in destination
    assert "latitude" in destination
    assert "longitude" in destination

    toilet = data["nearby_toilets"]["toilets"][0]
    assert "toilet_id" in toilet
    assert "name" in toilet
    assert "wheelchair_accessible" in toilet
    assert "distance_m" in toilet
    assert "latitude" in toilet
    assert "longitude" in toilet


@pytest.mark.asyncio
async def test_destination_not_found(client):
    session = create_mock_session(
        execute_results=[[]],  # empty result for destination query
    )
    override_session(session)

    response = await client.get("/api/v1/destinations/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Destination not found"


@pytest.mark.asyncio
async def test_custom_radius(client):
    session = create_mock_session(
        execute_results=[
            SAMPLE_DETAIL_DESTINATIONS,
            SAMPLE_TOILETS,
        ],
    )
    override_session(session)

    response = await client.get("/api/v1/destinations/1", params={"radius": 1000})

    assert response.status_code == 200
    assert response.json()["nearby_toilets"]["radius_m"] == 1000


@pytest.mark.asyncio
async def test_no_nearby_toilets(client):
    session = create_mock_session(
        execute_results=[
            SAMPLE_DETAIL_DESTINATIONS,
            [],  # no toilets found
        ],
    )
    override_session(session)

    response = await client.get("/api/v1/destinations/1", params={"radius": 100})

    assert response.status_code == 200
    data = response.json()
    assert data["nearby_toilets"]["count"] == 0
    assert data["nearby_toilets"]["toilets"] == []


@pytest.mark.asyncio
async def test_invalid_radius_too_low(client):
    response = await client.get("/api/v1/destinations/1", params={"radius": 50})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_radius_too_high(client):
    response = await client.get("/api/v1/destinations/1", params={"radius": 5000})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_destination_id_type(client):
    response = await client.get("/api/v1/destinations/abc")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_toilets_sorted_by_distance(client):
    session = create_mock_session(
        execute_results=[
            SAMPLE_DETAIL_DESTINATIONS,
            SAMPLE_TOILETS,
        ],
    )
    override_session(session)

    with mock_fetch_venue_details():
        response = await client.get("/api/v1/destinations/1")

    toilets = response.json()["nearby_toilets"]["toilets"]
    distances = [t["distance_m"] for t in toilets]
    assert distances == sorted(distances)


@pytest.mark.asyncio
async def test_default_pagination_values(client):
    session = create_mock_session(
        scalar_value=0,
        execute_results=[[]],
    )
    override_session(session)

    response = await client.get("/api/v1/destinations")
    data = response.json()

    assert data["limit"] == 20
    assert data["offset"] == 0


@pytest.mark.asyncio
async def test_default_radius_value(client):
    session = create_mock_session(
        execute_results=[
            SAMPLE_DETAIL_DESTINATIONS,
            [],
        ],
    )
    override_session(session)

    response = await client.get("/api/v1/destinations/1")

    assert response.json()["nearby_toilets"]["radius_m"] == 500

@pytest.mark.asyncio
async def test_destination_detail_includes_venue_details(client):
    """Destination with a place_id returns venue_details from Google Places."""
    session = create_mock_session(
        execute_results=[SAMPLE_DETAIL_DESTINATIONS, SAMPLE_TOILETS],
    )
    override_session(session)

    with mock_fetch_venue_details():
        response = await client.get("/api/v1/destinations/1")

    data = response.json()
    assert data["venue_details"] is not None
    assert "opening_hours" in data["venue_details"]
    assert "accessibility" in data["venue_details"]

@pytest.mark.asyncio
async def test_venue_details_opening_hours_shape(client):
    """Opening hours include open_now and weekday_text from Google."""
    session = create_mock_session(
        execute_results=[SAMPLE_DETAIL_DESTINATIONS, SAMPLE_TOILETS],
    )
    override_session(session)

    with mock_fetch_venue_details():
        response = await client.get("/api/v1/destinations/1")

    hours = response.json()["venue_details"]["opening_hours"]
    assert hours["open_now"] is False
    assert len(hours["weekday_text"]) == 7
    assert "Monday" in hours["weekday_text"][0]

@pytest.mark.asyncio
async def test_venue_details_accessibility_partial_data(client):
    """Accessibility flags include None for fields Google doesn't have data on."""
    session = create_mock_session(
        execute_results=[SAMPLE_DETAIL_DESTINATIONS, SAMPLE_TOILETS],
    )
    override_session(session)

    with mock_fetch_venue_details():
        response = await client.get("/api/v1/destinations/1")

    accessibility = response.json()["venue_details"]["accessibility"]
    assert accessibility["wheelchair_entrance"] is True
    assert accessibility["wheelchair_parking"] is True
    assert accessibility["wheelchair_restroom"] is True
    # Sample response intentionally omits seating to test missing data handling
    assert accessibility["wheelchair_seating"] is None

@pytest.mark.asyncio
async def test_destination_without_place_id_returns_null_venue_details(client):
    """A destination with no place_id returns venue_details: null."""
    session = create_mock_session(
        execute_results=[
            [SAMPLE_DESTINATION_WITHOUT_PLACE_ID],
            SAMPLE_TOILETS,
        ],
    )
    override_session(session)

    # No fetch_venue_details mock needed, the route should never call it
    # when place_id is None
    response = await client.get("/api/v1/destinations/2")

    assert response.status_code == 200
    assert response.json()["venue_details"] is None

@pytest.mark.asyncio
async def test_google_failure_returns_null_venue_details(client):
    """When Google returns None (failure), venue_details is null in the response."""
    session = create_mock_session(
        execute_results=[SAMPLE_DETAIL_DESTINATIONS, SAMPLE_TOILETS],
    )
    override_session(session)

    # Simulate Google call failure — fetch returns None
    with mock_fetch_venue_details(return_value=None):
        response = await client.get("/api/v1/destinations/1")

    # Endpoint still succeeds, just no venue_details
    assert response.status_code == 200
    assert response.json()["venue_details"] is None

@pytest.mark.asyncio
async def test_existing_destination_data_unchanged(client):
    """Adding venue_details didn't break existing destination + toilets fields."""
    session = create_mock_session(
        execute_results=[SAMPLE_DETAIL_DESTINATIONS, SAMPLE_TOILETS],
    )
    override_session(session)

    with mock_fetch_venue_details():
        response = await client.get("/api/v1/destinations/1")

    data = response.json()
    # Original Iter 1 fields are still present and correct
    assert data["destination"]["destination_id"] == 1
    assert data["destination"]["feature_name"] == "National Gallery of Victoria"
    assert data["nearby_toilets"]["count"] == 2

@pytest.mark.asyncio
async def test_transform_venue_details_full_response():
    """Full Google response is transformed correctly into our schema shape."""
    from app.services.google_places_transformer import transform_venue_details

    result = transform_venue_details(SAMPLE_GOOGLE_PLACES_RESPONSE)

    assert result["opening_hours"]["open_now"] is False
    assert len(result["opening_hours"]["weekday_text"]) == 7
    assert result["accessibility"]["wheelchair_entrance"] is True
    assert result["accessibility"]["wheelchair_seating"] is None

@pytest.mark.asyncio
async def test_transform_venue_details_no_opening_hours():
    """A response missing regularOpeningHours produces opening_hours: None."""
    from app.services.google_places_transformer import transform_venue_details

    response = {
        "accessibilityOptions": {"wheelchairAccessibleEntrance": True},
    }

    result = transform_venue_details(response)
    assert result["opening_hours"] is None
    assert result["accessibility"] is not None

@pytest.mark.asyncio
async def test_transform_venue_details_no_accessibility():
    """A response missing accessibilityOptions produces accessibility: None."""
    from app.services.google_places_transformer import transform_venue_details

    response = {
        "regularOpeningHours": {
            "openNow": True,
            "weekdayDescriptions": ["Monday: Open"],
        },
    }

    result = transform_venue_details(response)
    assert result["opening_hours"] is not None
    assert result["accessibility"] is None

@pytest.mark.asyncio
async def test_transform_venue_details_empty_response():
    """An empty Google response produces both fields as None."""
    from app.services.google_places_transformer import transform_venue_details

    result = transform_venue_details({})
    assert result["opening_hours"] is None
    assert result["accessibility"] is None