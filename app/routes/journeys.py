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
from app.schemas import JourneyPlanRequest, JourneyResponse
from app.services.otp import plan_journey, transform_itinerary

router = APIRouter(prefix="/api/v1/journeys", tags=["Journeys"])


@router.get("/plan", response_model=JourneyResponse)
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