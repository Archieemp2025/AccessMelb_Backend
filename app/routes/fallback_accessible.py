"""Steepness-enriched fallback endpoint.

Provides the same nearby-stops functionality as /journeys/fallback
but enriches each stop card with walking route steepness and an
LLM-generated plain-English summary.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Destination
from app.schemas import FallbackRequest
from app.fallback_steepness_schemas import FallbackAccessibleResponse
from app.services.otp import find_stops_by_radius, walk_to_stop, transform_fallback_response
from app.services.otp.transformers import (
    filter_accessible_stops,
    transform_fallback_stop,
    TARGET_STOP_COUNT,
)
from app.services.fallback_steepness import enrich_fallback_stops

# Same radius strategy as journeys.py
INITIAL_RADIUS_METRES = 500
EXPANDED_RADIUS_METRES = 800

# AS 1428.1 threshold for the all-exceed warning
_AS1428_THRESHOLD = 5.0

router = APIRouter(prefix="/api/v1/journeys", tags=["Journeys"])


@router.post("/fallback-accessible", response_model=FallbackAccessibleResponse)
async def fallback_accessible_journey(
    request: FallbackRequest,
    session: AsyncSession = Depends(get_session),
):
    """Show accessible stops with steepness data when user's location is unavailable.

    Same flow as /journeys/fallback, finds nearby stops, gets walking
    routes — then enriches each stop with gradient data from
    footpath_steepness and a Groq-generated plain-English summary.
    """
    # Look up destination, same pattern as journeys.py
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

    # Find nearby stops, same two-pass radius as journeys.py
    edges = await find_stops_by_radius(
        lat=dest_row.latitude,
        lon=dest_row.longitude,
        radius=INITIAL_RADIUS_METRES,
    )
    accessible_edges = filter_accessible_stops(edges)

    if len(accessible_edges) < TARGET_STOP_COUNT:
        edges = await find_stops_by_radius(
            lat=dest_row.latitude,
            lon=dest_row.longitude,
            radius=EXPANDED_RADIUS_METRES,
        )
        accessible_edges = filter_accessible_stops(edges)

    selected_edges = accessible_edges[:TARGET_STOP_COUNT]

    # Get walking routes, same sequential pattern as journeys.py
    # But we also keep the raw walking leg for polyline decoding
    stops_with_routes = []
    for edge in selected_edges:
        stop = edge["node"]["stop"]
        walking_leg = await walk_to_stop(
            from_lat=dest_row.latitude,
            from_lon=dest_row.longitude,
            to_lat=stop["lat"],
            to_lon=stop["lon"],
        )
        if walking_leg is None:
            continue

        transformed = transform_fallback_stop(edge, walking_leg)
        # Attach the raw walking leg so the steepness service can
        # decode its polyline. This is removed before the response.
        transformed["walking_route_raw"] = walking_leg
        stops_with_routes.append(transformed)

    # Enrich with steepness + LLM summaries
    enriched_stops = await enrich_fallback_stops(stops_with_routes, session)

    # Build the existing accessibility summary (warnings etc.)
    base_response = transform_fallback_response(destination_dict, stops_with_routes)

    # Check if all stops exceed the standard
    gradients_with_data = [
        s["walk_steepness"]["max_gradient_percent"]
        for s in enriched_stops
        if s["walk_steepness"]["max_gradient_percent"] is not None
    ]

    all_exceed = (
        len(gradients_with_data) > 0
        and all(g > _AS1428_THRESHOLD for g in gradients_with_data)
    )

    warning = None
    if all_exceed:
        flattest = min(gradients_with_data)
        warning = (
            f"All nearby walking routes exceed the recommended "
            f"{_AS1428_THRESHOLD}% gradient for wheelchair access. "
            f"The flattest walk is {flattest}%."
        )

    return {
        "destination": destination_dict,
        "stops": enriched_stops,
        "accessibility_summary": base_response["accessibility_summary"],
        "all_exceed_standard": all_exceed,
        "warning": warning,
    }