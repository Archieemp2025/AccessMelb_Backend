"""
Pydantic schemas for Fallback Steepness (No Location Shared).

Extends the existing fallback response with steepness and LLM summary
per stop. Reuses LastWalkSteepness from route_steepness_schemas.py
and the existing fallback schemas from schemas.py.
"""

from typing import Optional
from pydantic import BaseModel, Field

from app.schemas import (
    FallbackDestination,
    FallbackStopInfo,
    FallbackWalkingRoute,
    FallbackAccessibilitySummary,
)
from app.route_steepness_schemas import LastWalkSteepness


class FallbackStopWithSteepness(BaseModel):
    """A nearby stop with walking route, steepness data, and LLM summary."""

    stop: FallbackStopInfo
    walking_route: FallbackWalkingRoute
    walk_steepness: LastWalkSteepness = Field(
        ...,
        description="Steepness of the walking route from this stop to the destination.",
    )
    walk_summary: Optional[str] = Field(
        None,
        description="LLM-generated one-sentence description of the walk for wheelchair users. "
        "None if Groq is unavailable or the call failed.",
    )


class FallbackAccessibleResponse(BaseModel):
    """Response body for POST /api/v1/journeys/fallback-accessible.

    Same shape as the existing FallbackResponse but with steepness
    and LLM summary added to each stop. The destination and
    accessibility_summary fields are identical.
    """

    destination: FallbackDestination
    stops: list[FallbackStopWithSteepness]
    accessibility_summary: FallbackAccessibilitySummary
    all_exceed_standard: bool = Field(
        False,
        description="True if every stop's walking route exceeds 5%.",
    )
    warning: Optional[str] = Field(
        None,
        description="User-facing warning when all walking routes exceed the standard.",
    )