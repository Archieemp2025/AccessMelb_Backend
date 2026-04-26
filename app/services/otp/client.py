"""OpenTripPlanner GraphQL client.

Uses the `gql` library with httpx transport to call OTP's GraphQL endpoint.
Queries are stored as separate .graphql files under ./queries/ for easier
editing, syntax highlighting, and schema validation.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from gql import Client, gql
from gql.transport.exceptions import TransportError, TransportQueryError
from gql.transport.httpx import HTTPXAsyncTransport

from app.config import OTP_BASE_URL


logger = logging.getLogger(__name__)

# OTP GraphQL endpoint — resolved from env var at import time
OTP_GRAPHQL_URL = f"{OTP_BASE_URL}/otp/routers/default/index/graphql"

# All GTFS schedules are defined in Melbourne local time, so we translate
# user-supplied timestamps into this zone before passing to OTP.
MELBOURNE_TZ = ZoneInfo("Australia/Melbourne")

# Maximum seconds to wait for OTP to respond. If OTP is slow or unreachable,
# we'd rather fail fast and surface a friendly error than tie up FastAPI workers.
REQUEST_TIMEOUT = 10.0

# Load the GraphQL query from file at module import.
# Using a separate .graphql file gives us syntax highlighting and keeps
# query changes separate from Python logic in diffs.
_QUERIES_DIR = Path(__file__).parent / "queries"
_PLAN_JOURNEY_QUERY = gql((_QUERIES_DIR / "plan_journey.graphql").read_text())

_STOPS_BY_RADIUS_QUERY = gql((_QUERIES_DIR / "stops_by_radius.graphql").read_text())
_WALK_TO_STOP_QUERY = gql((_QUERIES_DIR / "walk_to_stop.graphql").read_text())

def _build_client() -> Client:
    """Construct a gql Client configured for OTP's GraphQL endpoint.

    A new client is built per request rather than reused, because gql's
    async client binds to an event loop on first use. FastAPI runs each
    request in its own async context, so per-request clients are the safe
    default. If performance becomes a concern we can introduce connection
    reuse later.
    """
    transport = HTTPXAsyncTransport(
        url=OTP_GRAPHQL_URL,
        timeout=REQUEST_TIMEOUT,
    )
    # fetch_schema_from_transport=False skips schema introspection on every
    # call. Introspection is useful at dev time for validation but adds a
    # round-trip at runtime — not worth it for a single-query client.
    return Client(transport=transport, fetch_schema_from_transport=False)


async def plan_journey(
    origin_lat: float,
    origin_lon: float,
    destination_lat: float,
    destination_lon: float,
    departure_time: Optional[datetime] = None,
) -> dict:
    """Plan a wheelchair-accessible journey via OTP.

    If departure_time is None, OTP plans for the current Melbourne time.
    Returns the first (and only) itinerary from OTP's response.

    Raises HTTPException on transport errors, GraphQL errors, or when
    no accessible journey is found.
    """
    # Convert the user's timestamp into Melbourne local time so OTP can
    # match it against GTFS service schedules. Use current time if none given.
    if departure_time is None:
        target_time = datetime.now(MELBOURNE_TZ)
    else:
        target_time = departure_time.astimezone(MELBOURNE_TZ)

    # GraphQL variables are passed separately from the query string.
    # This is the parameterised-query equivalent of SQL prepared statements —
    # prevents injection and keeps the query itself reusable.
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
        # gql's async context manager opens the HTTP connection and closes
        # it on exit. The execute() call handles GraphQL-specific error
        # semantics (errors field in response, not just HTTP status codes).
        async with client as session:
            result = await session.execute(
                _PLAN_JOURNEY_QUERY,
                variable_values=variables,
            )
    except TransportQueryError as e:
        # GraphQL returned an `errors` field — query was malformed or
        # something went wrong in OTP's resolver.
        logger.error(f"OTP GraphQL query error: {e}")
        raise HTTPException(
            status_code=503,
            detail="Journey planning is currently unavailable. Please try again shortly.",
        )
    except TransportError as e:
        # Transport-level error — connection refused, timeout, HTTP error.
        logger.error(f"OTP transport error: {e}")
        raise HTTPException(
            status_code=503,
            detail="Journey planning is currently unavailable. Please try again shortly.",
        )

    # Walk the response structure to extract itineraries. Using .get()
    # defensively here because a malformed OTP response shouldn't 500 our API.
    itineraries = result.get("plan", {}).get("itineraries", [])

    if not itineraries:
        # No journey found can mean the following: no services running at this time,
        # accessibility constraints exclude all options, or coordinates
        # are outside our service area. Surface a generic message to the
        # user rather than speculating about the cause.
        raise HTTPException(
            status_code=404,
            detail="No accessible journey found for this route and time. "
                   "Services may not be running, or accessibility constraints "
                   "may prevent a valid route.",
        )

    return itineraries[0]

async def find_stops_by_radius(
    lat: float,
    lon: float,
    radius: int,
    max_results: int = 20,
) -> list[dict]:
    """Find transit stops within a radius of a coordinate.

    Returns a list of stop edges ordered by distance from the centre point.
    Each edge contains the stop details and its distance from the query point.
    The caller is responsible for filtering by accessibility and selecting
    the top N results.

    Raises HTTPException on transport errors or GraphQL errors.
    """
    variables = {
        "lat": lat,
        "lon": lon,
        "radius": radius,
        "first": max_results,
    }

    client = _build_client()

    try:
        async with client as session:
            result = await session.execute(
                _STOPS_BY_RADIUS_QUERY,
                variable_values=variables,
            )
    except TransportQueryError as e:
        logger.error(f"OTP GraphQL query error on stopsByRadius: {e}")
        raise HTTPException(
            status_code=503,
            detail="Journey planning is currently unavailable. Please try again shortly.",
        )
    except TransportError as e:
        logger.error(f"OTP transport error on stopsByRadius: {e}")
        raise HTTPException(
            status_code=503,
            detail="Journey planning is currently unavailable. Please try again shortly.",
        )

    # Return the edges directly, the method filters and picks top N
    return result.get("stopsByRadius", {}).get("edges", [])

async def walk_to_stop(
    from_lat: float,
    from_lon: float,
    to_lat: float,
    to_lon: float,
) -> dict:
    """Plan a walking-only route between two coordinates.

    Used for the fallback endpoint to get walking routes between the
    destination and each nearby accessible stop. Returns the single
    walking leg as a dict.

    Raises HTTPException if no walking route is found.
    """
    variables = {
        "fromLat": from_lat,
        "fromLon": from_lon,
        "toLat": to_lat,
        "toLon": to_lon,
    }

    client = _build_client()

    try:
        async with client as session:
            result = await session.execute(
                _WALK_TO_STOP_QUERY,
                variable_values=variables,
            )
    except TransportQueryError as e:
        logger.error(f"OTP GraphQL query error on walk_to_stop: {e}")
        raise HTTPException(
            status_code=503,
            detail="Journey planning is currently unavailable. Please try again shortly.",
        )
    except TransportError as e:
        logger.error(f"OTP transport error on walk_to_stop: {e}")
        raise HTTPException(
            status_code=503,
            detail="Journey planning is currently unavailable. Please try again shortly.",
        )

    itineraries = result.get("plan", {}).get("itineraries", [])
    if not itineraries:
        # No walking route, possibly disconnected from pedestrian network.
        # Return None rather than raising.
        return None

    itinerary = itineraries[0]
    if not itinerary.get("legs"):
        return None

    return itinerary["legs"][0]