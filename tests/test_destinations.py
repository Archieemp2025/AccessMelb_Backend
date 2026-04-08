import pytest

from tests.conftest import (
    create_mock_session,
    override_session,
    SAMPLE_DESTINATIONS,
    SAMPLE_TOILETS,
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

    response = await client.get("/destinations")

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

    response = await client.get("/destinations")
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

    response = await client.get("/destinations", params={"category": "gallery"})

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

    response = await client.get("/destinations", params={"search": "national"})

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

    response = await client.get("/destinations", params={"limit": 1, "offset": 1})

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

    response = await client.get("/destinations", params={"search": "nonexistent"})

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
    assert data["destinations"] == []


@pytest.mark.asyncio
async def test_invalid_limit_too_high(client):
    response = await client.get("/destinations", params={"limit": 200})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_limit_too_low(client):
    response = await client.get("/destinations", params={"limit": 0})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_offset_negative(client):
    response = await client.get("/destinations", params={"offset": -1})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_combined_filters(client):
    session = create_mock_session(
        scalar_value=1,
        execute_results=[[SAMPLE_DESTINATIONS[0]]],
    )
    override_session(session)

    response = await client.get(
        "/destinations",
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
            [SAMPLE_DESTINATIONS[0]],  # destination query
            SAMPLE_TOILETS,            # nearby toilets query
        ],
    )
    override_session(session)

    response = await client.get("/destinations/1")

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
            [SAMPLE_DESTINATIONS[0]],
            SAMPLE_TOILETS[:1],
        ],
    )
    override_session(session)

    response = await client.get("/destinations/1")
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

    response = await client.get("/destinations/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Destination not found"


@pytest.mark.asyncio
async def test_custom_radius(client):
    session = create_mock_session(
        execute_results=[
            [SAMPLE_DESTINATIONS[0]],
            SAMPLE_TOILETS,
        ],
    )
    override_session(session)

    response = await client.get("/destinations/1", params={"radius": 1000})

    assert response.status_code == 200
    assert response.json()["nearby_toilets"]["radius_m"] == 1000


@pytest.mark.asyncio
async def test_no_nearby_toilets(client):
    session = create_mock_session(
        execute_results=[
            [SAMPLE_DESTINATIONS[0]],
            [],  # no toilets found
        ],
    )
    override_session(session)

    response = await client.get("/destinations/1", params={"radius": 100})

    assert response.status_code == 200
    data = response.json()
    assert data["nearby_toilets"]["count"] == 0
    assert data["nearby_toilets"]["toilets"] == []


@pytest.mark.asyncio
async def test_invalid_radius_too_low(client):
    response = await client.get("/destinations/1", params={"radius": 50})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_radius_too_high(client):
    response = await client.get("/destinations/1", params={"radius": 5000})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_destination_id_type(client):
    response = await client.get("/destinations/abc")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_toilets_sorted_by_distance(client):
    session = create_mock_session(
        execute_results=[
            [SAMPLE_DESTINATIONS[0]],
            SAMPLE_TOILETS,
        ],
    )
    override_session(session)

    response = await client.get("/destinations/1")
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

    response = await client.get("/destinations")
    data = response.json()

    assert data["limit"] == 20
    assert data["offset"] == 0


@pytest.mark.asyncio
async def test_default_radius_value(client):
    session = create_mock_session(
        execute_results=[
            [SAMPLE_DESTINATIONS[0]],
            [],
        ],
    )
    override_session(session)

    response = await client.get("/destinations/1")

    assert response.json()["nearby_toilets"]["radius_m"] == 500