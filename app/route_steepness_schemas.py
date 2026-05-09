"""
Pydantic schemas for Route Steepness (Journey Planner).

The AccessibleJourneyResponse wraps the existing JourneyResponse
(same shape the frontend already parses from /journeys/plan)
with steepness metadata added alongside.
"""

from typing import Optional
from pydantic import BaseModel, Field

from app.schemas import JourneyResponse


class LastWalkSteepness(BaseModel):
    """Steepness data for the last walking leg."""

    max_gradient_percent: Optional[float] = Field(
        None,
        description="Maximum gradient percentage along the last walking leg.",
    )
    within_standard: Optional[bool] = Field(
        None,
        description="True if max_gradient_percent <= 5.0 (AS 1428.1 Section 5.2).",
    )


class AccessibleJourneyResponse(BaseModel):
    """
    Response from POST /api/v1/journeys/plan-accessible.

    The journey field is the same JourneyResponse the frontend already
    parses from /journeys/plan — duration_seconds, walk_distance_metres,
    legs[], accessibility_summary, etc. Steepness fields are added
    alongside at the top level.
    """

    journey: JourneyResponse = Field(
        ...,
        description="The selected journey, same shape as /journeys/plan response.",
    )
    last_walk_steepness: LastWalkSteepness = Field(
        ...,
        description="Steepness of the last walking leg to the destination.",
    )
    all_exceed_standard: bool = Field(
        False,
        description="True if every candidate route's last walk exceeds 5%.",
    )
    warning: Optional[str] = Field(
        None,
        description="User-facing warning when all routes exceed the standard.",
    )