"""Transformers between OTP's GraphQL response shape and our API schemas.

OTP returns camelCase field names (GraphQL convention) and nests data
a few levels deep. The API uses snake_case (Python convention) and
flattens some structure for frontend convenience. This module also
computes backend-side enrichments: transfer waits, rail replacement
detection, and a journey-level accessibility summary.
"""

from datetime import datetime
from zoneinfo import ZoneInfo


MELBOURNE_TZ = ZoneInfo("Australia/Melbourne")

# These are product-level decisions about what constitutes a
# situations for wheelchair users. Centralised here so
# changing a threshold is a single edit.

LONG_WALK_METRES = 500 # wheelchair user walking more than this is "long"
VERY_LONG_WALK_METRES = 800  # approaching the maxWalkDistance limit
LONG_WAIT_SECONDS = 1200 # 20 minutes is a long platform wait
TARGET_STOP_COUNT = 3 # Minimum number of accessible stops near a destination.


def transform_itinerary(itinerary: dict) -> dict:
    """Transform an OTP itinerary into the shape our JourneyResponse expects.

    Adds backend-computed enrichments:
    - Transfer waits between legs
    - Rail replacement detection
    - Journey-level accessibility summary with warnings
    """
    legs = [_transform_leg(leg) for leg in itinerary["legs"]]

    # Compute transfer waits: for each leg except the first, how many
    # seconds the user waits between the previous leg ending and this
    # leg starting. Most commonly this is platform wait time between
    # transit services. We ignore gaps under 60 seconds as these are
    # just timing precision artifacts from OTP, not real waits.
    for i in range(1, len(legs)):
        prev_end = legs[i - 1]["end_time"]
        current_start = legs[i]["start_time"]
        wait_seconds = int((current_start - prev_end).total_seconds())
        if wait_seconds >= 60:
            legs[i]["wait_before_seconds"] = wait_seconds

    # Transfer count = transit legs minus 1. Walking legs don't count —
    # a walking leg IS the physical act of transferring, not a transfer itself.
    transit_legs = sum(1 for leg in legs if leg["mode"] != "WALK")
    transfers = max(0, transit_legs - 1)

    # Compute the accessibility summary across all legs
    accessibility_summary = _compute_accessibility_summary(legs)

    return {
        "duration_seconds": itinerary["duration"],
        "walk_distance_metres": itinerary["walkDistance"],
        "start_time": _ms_to_melbourne_datetime(itinerary["startTime"]),
        "end_time": _ms_to_melbourne_datetime(itinerary["endTime"]),
        "transfers": transfers,
        "legs": legs,
        "accessibility_summary": accessibility_summary,
    }


def _transform_leg(leg: dict) -> dict:
    """Flatten and rename fields from one OTP leg to match JourneyLeg schema.

    Also computes the `is_rail_replacement` flag based on the route name.
    """
    route_short_name = _nested_get(leg, "route", "shortName")

    # Rail replacement buses in Victoria's GTFS feed use route names
    # containing "Replacement Bus". This is a real scenario users hit
    # when rail works force buses onto the schedule.
    is_rail_replacement = (
        route_short_name is not None
        and "replacement" in route_short_name.lower()
    )

    return {
        "mode": leg["mode"],
        "start_time": _ms_to_melbourne_datetime(leg["startTime"]),
        "end_time": _ms_to_melbourne_datetime(leg["endTime"]),
        "duration_seconds": leg["duration"],
        "distance_metres": leg["distance"],
        "from_stop": _transform_place(leg["from"]),
        "to_stop": _transform_place(leg["to"]),
        "route_short_name": route_short_name,
        "route_long_name": _nested_get(leg, "route", "longName"),
        "agency_name": _nested_get(leg, "route", "agency", "name"),
        "trip_headsign": _nested_get(leg, "trip", "tripHeadsign"),
        "trip_wheelchair_accessible": _nested_get(leg, "trip", "wheelchairAccessible"),
        "intermediate_stops": [
            _transform_intermediate_stop(stop)
            for stop in (leg.get("intermediateStops") or [])
        ],
        "polyline": leg["legGeometry"]["points"],
        "wait_before_seconds": None, # populated later if applicable
        "is_rail_replacement": is_rail_replacement,
    }


def _transform_place(place: dict) -> dict:
    """Flatten a Place (leg's from/to field) into our JourneyStop schema."""
    stop = place.get("stop") or {}
    parent = stop.get("parentStation") or {}

    return {
        "gtfs_id": stop.get("gtfsId"),
        "name": place["name"],
        "lat": place["lat"],
        "lon": place["lon"],
        "wheelchair_boarding": stop.get("wheelchairBoarding"),
        "platform_code": stop.get("platformCode"),
        "parent_station_name": parent.get("name"),
    }


def _transform_intermediate_stop(stop: dict) -> dict:
    """Transform an intermediate stop (pass-through stop on a transit leg).

    OTP doesn't return lat/lon for intermediate stops in our query, it
    require a separate query to resolve.
    """
    return {
        "gtfs_id": stop.get("gtfsId"),
        "name": stop["name"],
        "lat": 0.0,
        "lon": 0.0,
        "wheelchair_boarding": stop.get("wheelchairBoarding"),
    }


def _compute_accessibility_summary(legs: list[dict]) -> dict:
    """Build the accessibility summary for the whole journey.

    Checks each leg for accessibility concerns and collects warnings.
    `fully_accessible` is True only when no warnings are raised.
    """
    warnings = []

    for idx, leg in enumerate(legs):
        # Walking legs can be long — flag ones that may be challenging
        if leg["mode"] == "WALK":
            distance = leg["distance_metres"]
            if distance >= VERY_LONG_WALK_METRES:
                warnings.append({
                    "type": "LONG_WALK",
                    "leg_index": idx,
                    "message": f"This walking leg is {int(distance)}m — near the maximum for an accessible route. Consider whether this distance is manageable.",
                })
            elif distance >= LONG_WALK_METRES:
                warnings.append({
                    "type": "LONG_WALK",
                    "leg_index": idx,
                    "message": f"This walking leg is {int(distance)}m — longer than typical.",
                })

        # Transit legs operating as rail replacement buses
        if leg["is_rail_replacement"]:
            warnings.append({
                "type": "RAIL_REPLACEMENT",
                "leg_index": idx,
                "message": "This service is a rail replacement bus. Accessibility of replacement buses varies — confirm with the driver before boarding.",
            })

        # Transit legs with unknown wheelchair accessibility on the trip itself
        trip_access = leg.get("trip_wheelchair_accessible")
        if leg["mode"] != "WALK" and trip_access == "NO_INFORMATION":
            warnings.append({
                "type": "UNKNOWN_ACCESSIBILITY",
                "leg_index": idx,
                "message": "Accessibility of this specific service is unconfirmed. Please verify with the operator before boarding.",
            })

        # Long waits before this leg
        wait = leg.get("wait_before_seconds")
        if wait is not None and wait >= LONG_WAIT_SECONDS:
            minutes = wait // 60
            warnings.append({
                "type": "LONG_WAIT",
                "leg_index": idx,
                "message": f"{minutes}-minute wait before this service. Consider arranging accessible seating while waiting.",
            })

    return {
        "fully_accessible": len(warnings) == 0,
        "warnings": warnings,
    }


def _ms_to_melbourne_datetime(milliseconds: int) -> datetime:
    """Convert OTP's Unix-millisecond timestamp to a Melbourne-local datetime."""
    return datetime.fromtimestamp(milliseconds / 1000, tz=MELBOURNE_TZ)


def _nested_get(d: dict, *keys):
    """Safely traverse nested dicts, returning None if any key is missing."""
    for key in keys:
        if d is None:
            return None
        d = d.get(key)
    return d

def filter_accessible_stops(edges: list[dict]) -> list[dict]:
    """Filter OTP stops-by-radius edges to accessible candidates.

    Most Victorian tram and bus stops have wheelchairBoarding = NO_INFORMATION
    because operators don't populate stop-level accessibility. We accept
    these alongside explicit POSSIBLE stops and surface the uncertainty
    via accessibility warnings. Only stops explicitly marked NOT_POSSIBLE
    are excluded.

    Also deduplicates by (name, parent_station) since GTFS often splits
    a single logical stop into inbound/outbound nodes with identical
    names — showing both to the user is just noise.
    """
    filtered = []
    seen_names = set()

    for edge in edges:
        stop = edge["node"]["stop"]

        # Exclude explicitly inaccessible stops
        if stop.get("wheelchairBoarding") == "NOT_POSSIBLE":
            continue

        # Deduplicate by stop name
        name_key = stop["name"]
        if name_key in seen_names:
            continue
        seen_names.add(name_key)

        filtered.append(edge)

    return filtered

def filter_accessible_stops(edges: list[dict]) -> list[dict]:
    """Filter OTP stops-by-radius edges to accessible candidates.

    Most Victorian tram and bus stops have wheelchairBoarding = NO_INFORMATION
    because operators don't populate stop-level accessibility. The product accept
    these alongside explicit POSSIBLE stops and surface the uncertainty
    via accessibility warnings. Only stops explicitly marked NOT_POSSIBLE
    are excluded.

    Also deduplicates by (name, parent_station) since GTFS often splits
    a single logical stop into inbound/outbound nodes with identical
    names, showing both to the user is just noise.
    """
    filtered = []
    seen_names = set()

    for edge in edges:
        stop = edge["node"]["stop"]

        # Exclude explicitly inaccessible stops
        if stop.get("wheelchairBoarding") == "NOT_POSSIBLE":
            continue

        # Deduplicate by stop name
        name_key = stop["name"]
        if name_key in seen_names:
            continue
        seen_names.add(name_key)

        filtered.append(edge)

    return filtered

def transform_fallback_stop(edge: dict, walking_leg: dict) -> dict:
    """Transform a stop edge + walking leg into the FallbackStop schema shape."""
    stop = edge["node"]["stop"]
    distance = edge["node"]["distance"]

    # Route short names for display. Some routes have no short name
    # (rare in Victoria's feed), fall back to the long name in that case.
    routes = []
    for route in stop.get("routes") or []:
        short = route.get("shortName") or route.get("longName") or "Unknown"
        if short not in routes:
            routes.append(short)

    # Sort: numeric routes in numeric order, then non-numeric alphabetically
    def _route_sort_key(route_name: str):
        # Try to convert to int; non-numeric routes get a large number so they sort last
        try:
            return (0, int(route_name))
        except ValueError:
            return (1, route_name)
        
    routes.sort(key=_route_sort_key)

    parent = stop.get("parentStation") or {}

    return {
        "stop": {
            "gtfs_id": stop["gtfsId"],
            "name": stop["name"],
            "lat": stop["lat"],
            "lon": stop["lon"],
            "mode": stop.get("vehicleMode"),
            "wheelchair_boarding": stop.get("wheelchairBoarding"),
            "parent_station_name": parent.get("name"),
            "routes": routes,
            "distance_metres": distance,
        },
        "walking_route": {
            "duration_seconds": walking_leg["duration"],
            "distance_metres": walking_leg["distance"],
            "polyline": walking_leg["legGeometry"]["points"],
        },
    }

def build_fallback_accessibility_summary(stops: list[dict]) -> dict:
    """Build an accessibility summary for the fallback response.

    Surfaces warnings when we couldn't find enough stops, when nearby
    stops have unknown accessibility, or when walks to those stops are long.
    """
    warnings = []

    # Warn if we found fewer stops than we aimed for
    if len(stops) < TARGET_STOP_COUNT:
        warnings.append({
            "type": "INSUFFICIENT_STOPS",
            "message": f"Only {len(stops)} accessible stop"
                       f"{'s' if len(stops) != 1 else ''} found nearby. "
                       f"You may need to widen your search area or consider "
                       f"a different destination.",
        })

    # Check each stop for individual warnings
    for idx, stop_with_route in enumerate(stops):
        stop = stop_with_route["stop"]
        walking_route = stop_with_route["walking_route"]

        # Unknown accessibility at the stop level
        if stop["wheelchair_boarding"] == "NO_INFORMATION":
            warnings.append({
                "type": "UNKNOWN_STOP_ACCESSIBILITY",
                "stop_index": idx,
                "message": f"{stop['name']} accessibility is unconfirmed. "
                           f"Check with the operator before relying on this stop.",
            })

        # Long walk from stop to destination
        distance = walking_route["distance_metres"]
        if distance >= VERY_LONG_WALK_METRES:
            warnings.append({
                "type": "LONG_WALK",
                "stop_index": idx,
                "message": f"{int(distance)}m walk from {stop['name']} to the "
                           f"destination — near the maximum for an accessible route.",
            })
        elif distance >= LONG_WALK_METRES:
            warnings.append({
                "type": "LONG_WALK",
                "stop_index": idx,
                "message": f"{int(distance)}m walk from {stop['name']} to the "
                           f"destination — longer than typical.",
            })

    return {
        "fully_accessible": all(
            w["type"] not in ("LONG_WALK", "UNKNOWN_STOP_ACCESSIBILITY")
            for w in warnings
        ),
        "warnings": warnings,
    }

def transform_fallback_response(
    destination: dict,
    stops_with_routes: list[dict],
) -> dict:
    """Build the complete fallback response from destination and stops data."""
    accessibility_summary = build_fallback_accessibility_summary(stops_with_routes)

    return {
        "destination": destination,
        "stops": stops_with_routes,
        "accessibility_summary": accessibility_summary,
    }