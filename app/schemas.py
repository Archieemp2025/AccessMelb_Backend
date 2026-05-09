from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, Literal


class DestinationSchema(BaseModel):
    destination_id: int
    feature_name: str
    category: str
    sub_theme: str
    latitude: float
    longitude: float


class DestinationListResponse(BaseModel):
    count: int
    limit: int
    offset: int
    destinations: list[DestinationSchema]


class ToiletSchema(BaseModel):
    toilet_id: int
    name: str
    wheelchair_accessible: str
    distance_m: float
    latitude: float
    longitude: float


class NearbyToiletsResponse(BaseModel):
    radius_m: int
    count: int
    toilets: list[ToiletSchema]


class OpeningHours(BaseModel):
    """Opening hours information for a venue."""
    open_now: Optional[bool] = Field(
        None,
        description="Whether the venue is open right now. None if unknown.",
    )
    weekday_text: list[str] = Field(
        default_factory=list,
        description='Human-readable hours per day, e.g. "Monday: 10:00 AM – 5:00 PM".',
    )

class WheelchairAccessibility(BaseModel):
    """Wheelchair accessibility flags for a venue.

    Each field is True/False/None. None means Google has no data for that
    feature, distinct from False which means it's been confirmed unavailable.
    """
    wheelchair_entrance: Optional[bool] = None
    wheelchair_parking: Optional[bool] = None
    wheelchair_restroom: Optional[bool] = None
    wheelchair_seating: Optional[bool] = None

class VenueDetails(BaseModel):
    """Live venue details from Google Places.

    Both fields can be None, opening_hours when Google has no hours data,
    accessibility when Google has no accessibility data. The whole VenueDetails
    object can also be None at the response level when:
    - The destination has no place_id in our database
    - The Google API call failed
    """
    opening_hours: Optional[OpeningHours] = None
    accessibility: Optional[WheelchairAccessibility] = None


class DestinationDetailResponse(BaseModel):
    destination: DestinationSchema
    nearby_toilets: NearbyToiletsResponse
    venue_details: Optional[VenueDetails] = None 


class Coordinates(BaseModel):
    """Latitude and longitude bounded to Greater Melbourne."""
    lat: float = Field(..., ge=-38.5, le=-37.4, description="Latitude")
    lon: float = Field(..., ge=144.5, le=145.6, description="Longitude")

class JourneyPlanRequest(BaseModel):
    """Request body for POST /api/v1/journeys/plan."""
    origin: Coordinates
    destination_id: int = Field(..., ge=1, description="Destination ID from catalog")
    departure_time: Optional[datetime] = Field(
        None,
        description="ISO 8601 departure time. If not provided, OTP uses 'now'.",
    )

class JourneyStop(BaseModel):
    """A stop along a transit leg."""
    gtfs_id: Optional[str] = None
    name: str
    lat: float
    lon: float
    wheelchair_boarding: Optional[Literal["POSSIBLE", "NOT_POSSIBLE", "NO_INFORMATION"]] = None
    platform_code: Optional[str] = None
    parent_station_name: Optional[str] = None

class JourneyLeg(BaseModel):
    """Single leg of a journey (walk, rail, tram, or bus segment)."""
    mode: Literal["WALK", "RAIL", "TRAM", "BUS", "SUBWAY"]
    start_time: datetime
    end_time: datetime
    duration_seconds: int
    distance_metres: float
    from_stop: JourneyStop
    to_stop: JourneyStop
    route_short_name: Optional[str] = None
    route_long_name: Optional[str] = None
    agency_name: Optional[str] = None
    trip_headsign: Optional[str] = None
    trip_wheelchair_accessible: Optional[Literal["POSSIBLE", "NOT_POSSIBLE", "NO_INFORMATION"]] = None
    intermediate_stops: list[JourneyStop] = []
    polyline: str = Field(..., description="Encoded polyline for map rendering")
    wait_before_seconds: Optional[int] = Field(
        None,
        description="Seconds waiting before this leg starts (e.g. platform wait before next train). "
                    "Null if no wait or this is the first leg.",
    )
    is_rail_replacement: bool = Field(
        False,
        description="True when this transit leg is operating as a rail replacement bus service. "
                    "Accessibility of replacement buses varies and should be confirmed with the operator.",
    )

class AccessibilityWarning(BaseModel):
    """A warning surfaced to the user about a specific leg of the journey."""
    type: Literal["LONG_WALK", "RAIL_REPLACEMENT", "UNKNOWN_ACCESSIBILITY", "LONG_WAIT"]
    leg_index: int = Field(..., description="Index of the leg this warning applies to")
    message: str = Field(..., description="Human-readable warning message")


class AccessibilitySummary(BaseModel):
    """Overall accessibility picture for the journey."""
    fully_accessible: bool = Field(
        ...,
        description="True only if all stops/trips are confirmed accessible with no warnings.",
    )
    warnings: list[AccessibilityWarning] = Field(
        default_factory=list,
        description="Per-leg warnings the user should know about.",
    )

class JourneyResponse(BaseModel):
    """Response body for POST /api/v1/journeys/plan."""
    duration_seconds: int
    walk_distance_metres: float
    start_time: datetime
    end_time: datetime
    transfers: int
    legs: list[JourneyLeg]
    accessibility_summary: AccessibilitySummary

class FallbackRequest(BaseModel):
    """Request body for POST /api/v1/journeys/fallback."""
    destination_id: int = Field(..., ge=1, description="Destination ID from catalog")

class FallbackDestination(BaseModel):
    """Destination summary for the fallback response."""
    id: int
    name: str
    category: str
    lat: float
    lon: float

class FallbackStopInfo(BaseModel):
    """A nearby accessible stop with transit information."""
    gtfs_id: str
    name: str
    lat: float
    lon: float
    mode: Optional[Literal["TRAM", "BUS", "RAIL", "SUBWAY"]] = None
    wheelchair_boarding: Optional[Literal["POSSIBLE", "NOT_POSSIBLE", "NO_INFORMATION"]] = None
    parent_station_name: Optional[str] = None
    routes: list[str] = Field(default_factory=list, description="Short route names serving this stop")
    distance_metres: int = Field(..., description="Straight-line distance to the destination")

class FallbackWalkingRoute(BaseModel):
    """Walking route from a stop to the destination."""
    duration_seconds: int
    distance_metres: float
    polyline: str = Field(..., description="Encoded polyline for map rendering")

class FallbackStopWithRoute(BaseModel):
    """A nearby stop paired with its walking route to the destination."""
    stop: FallbackStopInfo
    walking_route: FallbackWalkingRoute

class FallbackAccessibilityWarning(BaseModel):
    """Warning surfaced in the fallback response.

    Unlike journey warnings, these can be stop-level, journey-level, or
    about the absence of data (e.g. insufficient stops found).
    """
    type: Literal[
        "INSUFFICIENT_STOPS",
        "UNKNOWN_STOP_ACCESSIBILITY",
        "LONG_WALK",
    ]
    stop_index: Optional[int] = Field(None, description="Index into stops array when warning is stop-specific")
    message: str


class FallbackAccessibilitySummary(BaseModel):
    """Overall accessibility picture for the fallback suggestions."""
    fully_accessible: bool
    warnings: list[FallbackAccessibilityWarning] = Field(default_factory=list)

class FallbackResponse(BaseModel):
    """Response body for POST /api/v1/journeys/fallback."""
    destination: FallbackDestination
    stops: list[FallbackStopWithRoute]
    accessibility_summary: FallbackAccessibilitySummary

class GradientDistribution(BaseModel):
    within_standard_percent: float   # below 5%, within AS 1428.1 Section 5.2
    outside_standard_percent: float  # above 5%, exceeds AS 1428.1 Section 5.2
 
 
class SteepestSection(BaseModel):
    gradient_percent: float
    address: Optional[str] # None if address missing in source data
 
 
class TerrainResponse(BaseModel):
    data_available: bool
    radius_m: int
    rating: Optional[str]  # "mostly_accessible" | "partially_accessible" | "largely_inaccessible"
    gradient_distribution: Optional[GradientDistribution]
    steepest_section: Optional[SteepestSection]
    summary: Optional[str]
 