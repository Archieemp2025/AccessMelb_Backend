from typing import Optional

from fastapi import APIRouter, Query, Depends, HTTPException
from sqlalchemy import select, func, cast, Numeric
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2 import Geography

from app.database import get_session
from app.models import Destination, PublicToilet
from app.schemas import (
    DestinationListResponse,
    DestinationSchema,
    DestinationDetailResponse,
    NearbyToiletsResponse,
    ToiletSchema,
)

router = APIRouter(prefix="/destinations", tags=["Old-Destinations"])


@router.get("", response_model=DestinationListResponse)
async def get_destinations(
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    base_filter = select(Destination)

    if category:
        base_filter = base_filter.where(Destination.category == category)

    if search:
        base_filter = base_filter.where(Destination.feature_name.ilike(f"%{search}%"))

    count_query = select(func.count()).select_from(base_filter.subquery())
    total = await session.scalar(count_query)

    rows_query = (
        select(
            Destination.destination_id,
            Destination.feature_name,
            Destination.category,
            Destination.sub_theme,
            func.ST_Y(Destination.location).label("latitude"),
            func.ST_X(Destination.location).label("longitude"),
        )
        .where(base_filter.whereclause if base_filter.whereclause is not None else True)
        .order_by(Destination.feature_name)
        .limit(limit)
        .offset(offset)
    )

    result = await session.execute(rows_query)
    rows = result.all()

    return DestinationListResponse(
        count=total,
        limit=limit,
        offset=offset,
        destinations=[
            DestinationSchema(
                destination_id=row.destination_id,
                feature_name=row.feature_name,
                category=row.category,
                sub_theme=row.sub_theme,
                latitude=round(row.latitude, 8),
                longitude=round(row.longitude, 8),
            )
            for row in rows
        ],
    )


@router.get("/{destination_id}", response_model=DestinationDetailResponse)
async def get_destination(
    destination_id: int,
    radius: int = Query(500, ge=100, le=2000),
    session: AsyncSession = Depends(get_session),
):
    dest_result = await session.execute(
        select(
            Destination.destination_id,
            Destination.feature_name,
            Destination.category,
            Destination.sub_theme,
            func.ST_Y(Destination.location).label("latitude"),
            func.ST_X(Destination.location).label("longitude"),
        ).where(Destination.destination_id == destination_id)
    )
    dest_row = dest_result.first()

    if not dest_row:
        raise HTTPException(status_code=404, detail="Destination not found")

    # cross join with destination table, filtered to one destination
    # ST_DWithin with geography cast ensures radius is in metres
    toilet_result = await session.execute(
        select(
            PublicToilet.toilet_id,
            PublicToilet.name,
            PublicToilet.wheelchair_accessible,
            func.round(
                func.ST_Distance(
                    cast(PublicToilet.location, Geography),
                    cast(Destination.location, Geography),
                ).cast(Numeric),
                1,
            ).label("distance_m"),
            func.ST_Y(PublicToilet.location).label("latitude"),
            func.ST_X(PublicToilet.location).label("longitude"),
        )
        .where(Destination.destination_id == destination_id)
        .where(
            func.ST_DWithin(
                cast(PublicToilet.location, Geography),
                cast(Destination.location, Geography),
                radius,
            )
        )
        .order_by("distance_m")
    )
    toilet_rows = toilet_result.all()

    return DestinationDetailResponse(
        destination=DestinationSchema(
            destination_id=dest_row.destination_id,
            feature_name=dest_row.feature_name,
            category=dest_row.category,
            sub_theme=dest_row.sub_theme,
            latitude=round(dest_row.latitude, 8),
            longitude=round(dest_row.longitude, 8),
        ),
        nearby_toilets=NearbyToiletsResponse(
            radius_m=radius,
            count=len(toilet_rows),
            toilets=[
                ToiletSchema(
                    toilet_id=row.toilet_id,
                    name=row.name,
                    wheelchair_accessible=row.wheelchair_accessible,
                    distance_m=float(row.distance_m),
                    latitude=round(row.latitude, 8),
                    longitude=round(row.longitude, 8),
                )
                for row in toilet_rows
            ],
        ),
    )