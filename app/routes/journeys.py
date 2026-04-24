"""Journey planning endpoints.

Provides wheelchair-accessible journey planning via OpenTripPlanner.
Currently supports the full door-to-door journey when the user shares
their location. Fallback flow (no location) will be added separately.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Destination
from app.schemas import JourneyPlanRequest, JourneyResponse, FallbackRequest, FallbackResponse
from app.services.otp import plan_journey, transform_itinerary, find_stops_by_radius, walk_to_stop, transform_fallback_response
from app.services.otp.transformers import filter_accessible_stops, transform_fallback_stop, TARGET_STOP_COUNT

# Search radius for nearby stops in metres, using two-pass approach:
# start with a smaller radius for more relevant results, expand if
# didn't find enough results. 500m matches typical walking distance to transit,
# 800m is our absolute cap to keep journeys reasonable for wheelchair users.

INITIAL_RADIUS_METRES = 500
EXPANDED_RADIUS_METRES = 800

router = APIRouter(prefix="/api/v1/journeys", tags=["Journeys"])


@router.post("/plan", response_model=JourneyResponse)
async def plan_full_journey(
    request: JourneyPlanRequest,
    session: AsyncSession = Depends(get_session),
):
    """Plan a wheelchair-accessible journey from user's location to a destination.

    Expects origin coordinates (typically from browser geolocation) and
    a destination ID. The destination's coordinates are resolved from the
    database and passed to OTP along with accessibility parameters.
    """
    # Look up the destination's coordinates from the database. Frontend sends
    # us the destination ID rather than coordinates so the source of truth
    # for each venue's location stays server-side.
    result = await session.execute(
        select(
            func.ST_Y(Destination.location).label("latitude"),
            func.ST_X(Destination.location).label("longitude"),
        ).where(Destination.destination_id == request.destination_id)
    )
    dest = result.first()

    if not dest:
        raise HTTPException(status_code=404, detail="Destination not found")

    # Call OTP with the user's origin and the resolved destination.
    # The OTP client handles timezone conversion and accessibility parameters.
    itinerary = await plan_journey(
        origin_lat=request.origin.lat,
        origin_lon=request.origin.lon,
        destination_lat=dest.latitude,
        destination_lon=dest.longitude,
        departure_time=request.departure_time,
    )

    # Transform OTP's camelCase, ms-timestamp response into the snake_case
    # schema. The transform also computes transfer count from the leg list.
    return transform_itinerary(itinerary)

@router.post("/fallback", response_model=FallbackResponse)
async def fallback_journey(
    request: FallbackRequest,
    session: AsyncSession = Depends(get_session),
):
    """Show accessible stops near a destination when the user's location is unavailable.

    Used when the user declines browser geolocation or it fails. Returns up to 3
    nearby accessible stops with walking routes from each stop to the destination,
    giving the user enough context to plan their own approach based on their origin.
    """
    # Look up destination details from the database
    result = await session.execute(
        select(
            Destination.destination_id,
            Destination.feature_name,
            Destination.category,
            func.ST_Y(Destination.location).label("latitude"),
            func.ST_X(Destination.location).label("longitude"),
        ).where(Destination.destination_id == request.destination_id)
    )
    dest_row = result.first()

    if not dest_row:
        raise HTTPException(status_code=404, detail="Destination not found")

    destination_dict = {
        "id": dest_row.destination_id,
        "name": dest_row.feature_name,
        "category": dest_row.category,
        "lat": dest_row.latitude,
        "lon": dest_row.longitude,
    }

    # Try the initial radius first — prefer close stops
    edges = await find_stops_by_radius(
        lat=dest_row.latitude,
        lon=dest_row.longitude,
        radius=INITIAL_RADIUS_METRES,
    )
    accessible_edges = filter_accessible_stops(edges)

    # Expand the search if enough stops not found
    if len(accessible_edges) < TARGET_STOP_COUNT:
        edges = await find_stops_by_radius(
            lat=dest_row.latitude,
            lon=dest_row.longitude,
            radius=EXPANDED_RADIUS_METRES,
        )
        accessible_edges = filter_accessible_stops(edges)

    # Take the top N edges are already sorted by distance from OTP
    selected_edges = accessible_edges[:TARGET_STOP_COUNT]

    # Fetch walking routes for each stop. Sequential calls by design
    # three short walking queries against localhost OTP is fast enough that
    # parallelising with asyncio.gather would be premature optimisation.
    stops_with_routes = []
    for edge in selected_edges:
        stop = edge["node"]["stop"]
        walking_leg = await walk_to_stop(
            from_lat=dest_row.latitude,
            from_lon=dest_row.longitude,
            to_lat=stop["lat"],
            to_lon=stop["lon"],
        )
        # Skip stops with no walkable route
        # disconnected from the pedestrian network in OSM.
        if walking_leg is None:
            continue
        stops_with_routes.append(transform_fallback_stop(edge, walking_leg))

    return transform_fallback_response(destination_dict, stops_with_routes)