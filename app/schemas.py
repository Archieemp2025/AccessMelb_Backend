from pydantic import BaseModel, Field
from typing import Optional


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

