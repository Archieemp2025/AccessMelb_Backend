"""Steepness-aware journey planning endpoint.

Provides wheelchair-accessible journey planning with steepness-based
route selection. Fetches 3 itineraries from OTP, compares the last
walking leg of each against footpath_steepness data, and returns the
best option using AS 1428.1 Section 5.2 as the threshold.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import Destination
from app.schemas import JourneyPlanRequest
from app.route_steepness_schemas import AccessibleJourneyResponse
from app.services.route_steepness import select_best_itinerary


router = APIRouter(prefix="/api/v1/journeys", tags=["Journeys"])


@router.post("/plan-accessible", response_model=AccessibleJourneyResponse)
async def plan_accessible_journey(
    request: JourneyPlanRequest,
    session: AsyncSession = Depends(get_session),
):
    """Plan a wheelchair-accessible journey with steepness-aware route selection.

    Accepts the same request body as /journeys/plan (origin coordinates +
    destination_id). Returns the best itinerary based on last-walk steepness,
    in the same JourneyResponse shape the frontend already parses, with
    steepness metadata added alongside.
    """
    # Look up destination coordinates, same pattern as journeys.py
    result = await session.execute(
        select(
            func.ST_Y(Destination.location).label("latitude"),
            func.ST_X(Destination.location).label("longitude"),
        ).where(Destination.destination_id == request.destination_id)
    )
    dest = result.first()

    if not dest:
        raise HTTPException(status_code=404, detail="Destination not found")

    # Select best itinerary based on steepness
    return await select_best_itinerary(
        origin_lat=request.origin.lat,
        origin_lon=request.origin.lon,
        destination_lat=dest.latitude,
        destination_lon=dest.longitude,
        departure_time=request.departure_time,
        session=session,
    )