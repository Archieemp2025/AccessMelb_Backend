"""
Pydantic schemas for Route Steepness (Journey Planner).

The AccessibleJourneyResponse wraps the existing JourneyResponse
(same shape the frontend already parses from /journeys/plan)
with steepness metadata added alongside.
"""

from typing import Optional
from pydantic import BaseModel, Field

from app.schemas import JourneyResponse


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
 
 
class NearbyToiletInfo(BaseModel):
    """An accessible toilet near the destination."""
 
    toilet_id: int
    name: str
    wheelchair_accessible: str = "yes"
    distance_from_destination_m: float = Field(
        ...,
        description="Straight-line distance from the destination in metres.",
    )
    lat: float
    lon: float
 
 
class ToiletWalkingRoute(BaseModel):
    """Walking route from the alighting stop to a toilet."""
 
    duration_seconds: int
    distance_metres: float
    polyline: str = Field(
        ...,
        description="Encoded polyline for map rendering.",
    )
 
 
class ToiletWithRoute(BaseModel):
    """A toilet paired with walking routes from the alighting stop and to the destination."""
 
    toilet: NearbyToiletInfo
    route_from_alighting_stop: Optional[ToiletWalkingRoute] = Field(
        None,
        description="Walking route from the alighting stop to this toilet. "
        "None if OTP couldn't find a walking route.",
    )
    route_to_destination: Optional[ToiletWalkingRoute] = Field(
        None,
        description="Walking route from this toilet to the destination. "
        "None if OTP couldn't find a walking route.",
    )
 
 
class AccessibleJourneyResponse(BaseModel):
    """
    Response from POST /api/v1/journeys/plan-accessible.
 
    The journey field is the same JourneyResponse the frontend already
    parses from /journeys/plan — duration_seconds, walk_distance_metres,
    legs[], accessibility_summary, etc. Steepness fields and nearby
    toilet routes are added alongside at the top level.
    """
 
    journey: JourneyResponse = Field(
        ...,
        description="The selected journey — same shape as /journeys/plan response.",
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
    nearby_toilets: list[ToiletWithRoute] = Field(
        default_factory=list,
        description="Up to 3 accessible toilets near the destination with "
        "walking routes from the alighting stop.",
    )