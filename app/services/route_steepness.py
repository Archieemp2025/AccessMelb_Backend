"""Route steepness service for Journey Planner.

Selects the best OTP itinerary based on last-walking-leg steepness.

Decision logic:
  1. Request 3 itineraries from OTP via plan_journey_multiple.graphql.
  2. For each, decode the last walking leg polyline and query
     footpath_steepness within a 30m buffer of that polyline.
  3. If any itinerary has last leg <= 5% (AS 1428.1 Section 5.2):
     Among those, pick the fastest transit time.
  4. If all itineraries exceed 5%:
     Pick the lowest max gradient, attach a warning.
  5. Transform the selected itinerary using the existing transform_itinerary
     and return it alongside steepness metadata.

"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo
 
from fastapi import HTTPException
from gql import Client, gql
from gql.transport.exceptions import TransportError, TransportQueryError
from gql.transport.httpx import HTTPXAsyncTransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
 
from app.config import OTP_BASE_URL
from app.services.otp.transformers import transform_itinerary
 
logger = logging.getLogger(__name__)
 
# OTP GraphQL endpoint — same as client.py
OTP_GRAPHQL_URL = f"{OTP_BASE_URL}/otp/routers/default/index/graphql"
MELBOURNE_TZ = ZoneInfo("Australia/Melbourne")
REQUEST_TIMEOUT = 10.0
 
# Load the 3-itinerary query at module import — same pattern as client.py
_QUERIES_DIR = Path(__file__).parent / "otp" / "queries"
_PLAN_MULTIPLE_QUERY = gql(
    (_QUERIES_DIR / "plan_journey_multiple.graphql").read_text()
)
 
# AS 1428.1 Section 5.2 — maximum gradient for accessible paths of travel
_AS1428_THRESHOLD = 5.0
 
# Buffer distance in metres around the walking polyline for spatial query
_BUFFER_METRES = 30
 
 
def _build_client() -> Client:
    """Construct a gql Client — same pattern as otp/client.py."""
    transport = HTTPXAsyncTransport(
        url=OTP_GRAPHQL_URL,
        timeout=REQUEST_TIMEOUT,
    )
    return Client(transport=transport, fetch_schema_from_transport=False)
 
 
async def _fetch_multiple_itineraries(
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
    departure_time: Optional[datetime] = None,
) -> list[dict]:
    """Fetch 3 itineraries from OTP for steepness comparison.
 
    Same logic as otp/client.py plan_journey() but uses the
    plan_journey_multiple.graphql query (numItineraries: 3)
    and returns the full list instead of just the first.
    """
    if departure_time is None:
        target_time = datetime.now(MELBOURNE_TZ)
    else:
        target_time = departure_time.astimezone(MELBOURNE_TZ)
 
    variables = {
        "fromLat": origin_lat,
        "fromLon": origin_lon,
        "toLat": destination_lat,
        "toLon": destination_lon,
        "date": target_time.strftime("%Y-%m-%d"),
        "time": target_time.strftime("%H:%M:%S"),
    }
 
    client = _build_client()
 
    try:
        async with client as session:
            result = await session.execute(
                _PLAN_MULTIPLE_QUERY,
                variable_values=variables,
            )
    except TransportQueryError as e:
        logger.error(f"OTP GraphQL query error (multiple): {e}")
        raise HTTPException(
            status_code=503,
            detail="Journey planning is currently unavailable. Please try again shortly.",
        )
    except TransportError as e:
        logger.error(f"OTP transport error (multiple): {e}")
        raise HTTPException(
            status_code=503,
            detail="Journey planning is currently unavailable. Please try again shortly.",
        )
 
    itineraries = result.get("plan", {}).get("itineraries", [])
 
    if not itineraries:
        raise HTTPException(
            status_code=404,
            detail="No accessible journey found for this route and time. "
                   "Services may not be running, or accessibility constraints "
                   "may prevent a valid route.",
        )
 
    return itineraries
 
  
def _decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Decode a Google Encoded Polyline into (lon, lat) tuples.
 
    Returns lon/lat order for PostGIS ST_MakePoint.
    """
    points = []
    index = 0
    lat = 0
    lon = 0
    length = len(encoded)
 
    while index < length:
        shift = 0
        result = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        lat += (~(result >> 1) if (result & 1) else (result >> 1))
 
        shift = 0
        result = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        lon += (~(result >> 1) if (result & 1) else (result >> 1))
 
        points.append((lon / 1e5, lat / 1e5))
 
    return points
 
  
def _extract_last_walk_leg(itinerary: dict) -> Optional[dict]:
    """Extract the last walking leg from an OTP itinerary.
 
    The last walking leg is the final leg where mode == WALK and
    to.stop is None (destination, not a transit stop).
    """
    legs = itinerary.get("legs", [])
    if not legs:
        return None
 
    last_leg = legs[-1]
    if last_leg.get("mode") == "WALK" and last_leg.get("to", {}).get("stop") is None:
        return last_leg
 
    # Edge case: walk backwards to find last WALK leg
    for leg in reversed(legs):
        if leg.get("mode") == "WALK":
            return leg
 
    return None
 
 
async def _compute_steepness(
    last_leg: dict,
    session: AsyncSession,
) -> Optional[float]:
    """Compute max gradient along a walking leg's polyline.
 
    Returns the max gradient_percent as a float, or None if no data.
    """
    geometry = last_leg.get("legGeometry", {})
    encoded = geometry.get("points")
 
    if not encoded:
        return None
 
    points = _decode_polyline(encoded)
    if len(points) < 2:
        return None
 
    # Build EWKT LINESTRING in (lon, lat) order for PostGIS
    coords = ", ".join(f"{lon} {lat}" for lon, lat in points)
    linestring_wkt = f"SRID=4326;LINESTRING({coords})"
 
    # Buffer the polyline by 30m and find intersecting footpath points.
    # The GIST index on footpath_steepness.geom makes this fast —
    # narrows to bounding box first, precise check on ~10-50 rows.
    query = text("""
        SELECT MAX(gradient_percent) AS max_gradient
        FROM footpath_steepness
        WHERE gradient_percent IS NOT NULL
          AND gradient_percent <= 30
          AND ST_Intersects(
              geom::geography,
              ST_Buffer(
                  ST_GeomFromEWKT(:linestring)::geography,
                  :buffer_m
              )
          )
    """)
 
    result = await session.execute(
        query,
        {"linestring": linestring_wkt, "buffer_m": _BUFFER_METRES},
    )
    row = result.mappings().first()
 
    if not row or row["max_gradient"] is None:
        return None
 
    return round(float(row["max_gradient"]), 1)
 
  
async def select_best_itinerary(
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
    departure_time: Optional[datetime],
    session: AsyncSession,
) -> dict:
    """Main entry point, called from the router.
 
    1. Fetches 3 itineraries from OTP.
    2. Computes last-walk steepness for each concurrently.
    3. Selects the best using the AS 1428.1 decision logic.
    4. Transforms the winner using the existing transform_itinerary.
    5. Returns the response dict matching AccessibleJourneyResponse.
    """
 
    # Step 1: Fetch 3 itineraries
    itineraries = await _fetch_multiple_itineraries(
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        destination_lat=destination_lat,
        destination_lon=destination_lon,
        departure_time=departure_time,
    )
 
    # Step 2: Extract last walk legs and compute steepness in parallel
    last_legs = [_extract_last_walk_leg(itin) for itin in itineraries]
 
    steepness_tasks = []
    for leg in last_legs:
        if leg is not None:
            steepness_tasks.append(_compute_steepness(leg, session))
        else:
            steepness_tasks.append(_return_none())
 
    max_gradients = await asyncio.gather(*steepness_tasks)
 
    # Step 3: Pair itineraries with their steepness
    paired = list(zip(itineraries, max_gradients))
 
    # Separate into buckets
    within_standard = [
        (itin, grad)
        for itin, grad in paired
        if grad is not None and grad <= _AS1428_THRESHOLD
    ]
    exceeds_standard = [
        (itin, grad)
        for itin, grad in paired
        if grad is not None and grad > _AS1428_THRESHOLD
    ]
 
    # Step 4: Selection logic
    all_exceed = False
    warning = None
 
    if within_standard:
        # Pick fastest transit among routes with manageable last walk
        best_itin, best_grad = min(
            within_standard,
            key=lambda pair: pair[0].get("duration", float("inf")),
        )
    elif exceeds_standard:
        # Pick lowest gradient — all exceed the standard
        best_itin, best_grad = min(
            exceeds_standard,
            key=lambda pair: pair[1],
        )
        all_exceed = True
        warning = (
            f"All available routes have a final walk that exceeds the "
            f"recommended {_AS1428_THRESHOLD}% gradient for wheelchair access. "
            f"The route shown has the lowest gradient at {best_grad}%."
        )
    else:
        # No steepness data — return fastest
        best_itin = min(
            itineraries,
            key=lambda itin: itin.get("duration", float("inf")),
        )
        best_grad = None
 
    # Step 5: Transform the winner using the existing transformer
    transformed = transform_itinerary(best_itin)
 
    # Step 6: Get nearby toilet routes from the alighting stop
    from app.services.toilet_routes import get_toilet_routes
 
    toilet_routes = await get_toilet_routes(
        itinerary=best_itin,
        dest_lat=destination_lat,
        dest_lon=destination_lon,
        session=session,
    )
 
    # Step 7: Build response matching AccessibleJourneyResponse schema
    steepness_data = {}
    if best_grad is not None:
        steepness_data = {
            "max_gradient_percent": best_grad,
            "within_standard": best_grad <= _AS1428_THRESHOLD,
        }
 
    return {
        "journey": transformed,
        "last_walk_steepness": steepness_data if steepness_data else {
            "max_gradient_percent": None,
            "within_standard": None,
        },
        "all_exceed_standard": all_exceed,
        "warning": warning,
        "nearby_toilets": toilet_routes,
    }
 
 
async def _return_none():
    """Async wrapper returning None, used in asyncio.gather for legs without data."""
    return None
 