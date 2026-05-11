"""Nearby toilet routes service.

Finds accessible toilets near a destination and computes walking routes
from the alighting stop (where the user gets off transit) to each toilet
via OTP.

Used by the plan-accessible endpoint to add toilet route data alongside
the journey and steepness information.

This file does NOT modify any existing service or router.
"""

import asyncio
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.otp import walk_to_stop

logger = logging.getLogger(__name__)

# Maximum number of toilet routes to compute
_MAX_TOILETS = 3

# Search radius in metres around the destination
_TOILET_RADIUS_M = 500


async def find_nearby_accessible_toilets(
    dest_lat: float,
    dest_lon: float,
    session: AsyncSession,
    radius_m: int = _TOILET_RADIUS_M,
    limit: int = _MAX_TOILETS,
) -> list[dict]:
    """Find wheelchair-accessible toilets near a destination.

    Queries the public_toilet table using ST_DWithin with geography
    cast for real-world metres. Same spatial pattern as the destination
    detail endpoint but filtered to wheelchair_accessible = 'yes' only.

    Returns a list of dicts with toilet_id, name, lat, lon, and
    distance_from_destination_m — ordered by distance ascending.
    """
    query = text("""
        SELECT
            toilet_id,
            name,
            ST_Y(location) AS lat,
            ST_X(location) AS lon,
            ROUND(
                ST_Distance(
                    location::geography,
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                )::numeric,
                1
            ) AS distance_m
        FROM public_toilet
        WHERE wheelchair_accessible = 'yes'
          AND ST_DWithin(
              location::geography,
              ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
              :radius
          )
        ORDER BY distance_m
        LIMIT :limit
    """)

    result = await session.execute(
        query,
        {
            "lat": dest_lat,
            "lon": dest_lon,
            "radius": radius_m,
            "limit": limit,
        },
    )
    rows = result.mappings().all()

    return [
        {
            "toilet_id": row["toilet_id"],
            "name": row["name"],
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "distance_from_destination_m": float(row["distance_m"]),
        }
        for row in rows
    ]


def _extract_alighting_stop(itinerary: dict) -> Optional[dict]:
    """Extract the alighting stop from an OTP itinerary.

    The alighting stop is the 'from' of the last walking leg — the
    transit stop where the user gets off before walking to the
    destination. Returns None if no transit leg exists (walk-only
    journey).
    """
    legs = itinerary.get("legs", [])
    if not legs:
        return None

    # Find the last walking leg (to destination)
    last_leg = legs[-1]
    if last_leg.get("mode") == "WALK" and last_leg.get("to", {}).get("stop") is None:
        # The 'from' of the last walk is the alighting stop
        from_place = last_leg.get("from", {})
        stop = from_place.get("stop")
        if stop:
            return {
                "lat": from_place["lat"],
                "lon": from_place["lon"],
                "name": from_place.get("name"),
                "gtfs_id": stop.get("gtfsId"),
            }

    # Fallback: if the last leg isn't a walk, look for the last
    # transit leg's 'to' stop
    for leg in reversed(legs):
        if leg.get("mode") != "WALK":
            to_place = leg.get("to", {})
            stop = to_place.get("stop")
            if stop:
                return {
                    "lat": to_place["lat"],
                    "lon": to_place["lon"],
                    "name": to_place.get("name"),
                    "gtfs_id": stop.get("gtfsId"),
                }

    return None


async def _get_toilet_walking_route(
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
) -> Optional[dict]:
    """Get a walking route from the alighting stop to a toilet via OTP.

    Uses the existing walk_to_stop function from the OTP client.
    Returns the walking route dict or None if no route found.
    """
    try:
        walking_leg = await walk_to_stop(
            from_lat=from_lat,
            from_lon=from_lon,
            to_lat=to_lat,
            to_lon=to_lon,
        )

        if walking_leg is None:
            return None

        return {
            "duration_seconds": walking_leg["duration"],
            "distance_metres": walking_leg["distance"],
            "polyline": walking_leg["legGeometry"]["points"],
        }
    except Exception as e:
        logger.warning(f"Failed to get toilet walking route: {type(e).__name__}: {e}")
        return None


async def get_toilet_routes(
    itinerary: dict,
    dest_lat: float,
    dest_lon: float,
    session: AsyncSession,
) -> list[dict]:
    """Main entry point, find accessible toilets and compute routes.

    Called from the plan-accessible router after the journey is selected.

    Steps:
    1. Extract the alighting stop from the selected itinerary.
    2. Find accessible toilets near the destination (up to 3).
    3. For each toilet, get OTP walking route from the alighting stop.
    4. Return enriched toilet data with routes.

    If there's no alighting stop (walk-only journey), routes are
    computed from the destination coordinates instead.
    """
    # Step 1: Find the alighting stop
    alighting = _extract_alighting_stop(itinerary)

    # If walk-only journey, use destination as the starting point
    from_lat = alighting["lat"] if alighting else dest_lat
    from_lon = alighting["lon"] if alighting else dest_lon

    # Step 2: Find nearby accessible toilets
    toilets = await find_nearby_accessible_toilets(
        dest_lat=dest_lat,
        dest_lon=dest_lon,
        session=session,
    )

    if not toilets:
        return []

    # Step 3: Get walking routes concurrently
    # For each toilet we need two routes:
    #   a) Alighting stop to toilet (how to get there after getting off transit)
    #   b) Toilet to destination (how to continue to the destination after)
    from_stop_tasks = [
        _get_toilet_walking_route(
            from_lat=from_lat,
            from_lon=from_lon,
            to_lat=toilet["lat"],
            to_lon=toilet["lon"],
        )
        for toilet in toilets
    ]
    to_dest_tasks = [
        _get_toilet_walking_route(
            from_lat=toilet["lat"],
            from_lon=toilet["lon"],
            to_lat=dest_lat,
            to_lon=dest_lon,
        )
        for toilet in toilets
    ]

    # Run all routes concurrently, both sets in one gather call
    all_routes = await asyncio.gather(*from_stop_tasks, *to_dest_tasks)

    # Split results back into two lists
    routes_from_stop = all_routes[:len(toilets)]
    routes_to_dest = all_routes[len(toilets):]

    # Step 4: Pair toilets with both routes
    result = []
    for i, toilet in enumerate(toilets):
        result.append({
            "toilet": {
                "toilet_id": toilet["toilet_id"],
                "name": toilet["name"],
                "wheelchair_accessible": "yes",
                "distance_from_destination_m": toilet["distance_from_destination_m"],
                "lat": toilet["lat"],
                "lon": toilet["lon"],
            },
            "route_from_alighting_stop": routes_from_stop[i],
            "route_to_destination": routes_to_dest[i],
        })

    return result