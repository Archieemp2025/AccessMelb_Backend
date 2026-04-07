from pydantic import BaseModel


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


class DestinationDetailResponse(BaseModel):
    destination: DestinationSchema
    nearby_toilets: NearbyToiletsResponse