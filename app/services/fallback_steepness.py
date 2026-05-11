"""Fallback steepness service (No Location Shared).

Enriches the existing fallback stop cards with:
  1. Walking route steepness (max gradient from footpath_steepness)
  2. LLM-generated one-sentence summary per stop (Groq, llama-3.3-70b)

Reuses _decode_polyline and spatial query pattern from route_steepness.py.
Does NOT modify any existing service file.

Groq call follows the same graceful degradation pattern as terrain.py:
  - If GROQ_API_KEY is not set, summary is None
  - If the API call fails, summary is None
  - The stop card still renders with the steepness badge regardless
"""

import asyncio
import os
import logging
from typing import Optional

from groq import Groq
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.route_steepness import _decode_polyline

logger = logging.getLogger(__name__)

# AS 1428.1 Section 5.2, same threshold used across all terrain features
_AS1428_THRESHOLD = 5.0

# Buffer distance in metres around the walking polyline
_BUFFER_METRES = 30


async def compute_walk_steepness(
    walking_leg: dict,
    session: AsyncSession,
) -> Optional[float]:
    """Compute max gradient along a walking leg's polyline.

    Same spatial logic as route_steepness._compute_steepness but
    defined here to keep the fallback service self-contained
    while reusing the polyline decoder.

    Returns max gradient_percent as a float, or None if no data.
    """
    geometry = walking_leg.get("legGeometry", {})
    encoded = geometry.get("points")

    if not encoded:
        return None

    points = _decode_polyline(encoded)
    if len(points) < 2:
        return None

    coords = ", ".join(f"{lon} {lat}" for lon, lat in points)
    linestring_wkt = f"SRID=4326;LINESTRING({coords})"

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


async def generate_walk_summary(
    stop_name: str,
    distance_metres: float,
    duration_seconds: int,
    max_gradient: Optional[float],
) -> Optional[str]:
    """Generate a one-sentence plain-English summary of a walking route.

    Uses Groq (llama-3.3-70b-versatile), same model and pattern as
    terrain.py. Returns None on any failure, the stop card still
    renders with the steepness badge.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None

    # Build gradient context
    if max_gradient is None:
        gradient_line = "Gradient data is not available for this walking route."
    elif max_gradient <= _AS1428_THRESHOLD:
        gradient_line = (
            f"The maximum gradient is {max_gradient}%, which is within "
            f"the Australian wheelchair accessibility standard (5%)."
        )
    else:
        gradient_line = (
            f"The maximum gradient is {max_gradient}%, which exceeds "
            f"the Australian wheelchair accessibility standard (5%). "
            f"This may be challenging for some wheelchair users."
        )

    walk_minutes = max(1, duration_seconds // 60)
    distance_int = int(distance_metres)

    prompt = f"""You are describing a specific route from a tram/bus stop to a destination for a wheelchair user in Melbourne. Write exactly 1 sentence that is UNIQUE to this specific route.

                Route details:
                - From: {stop_name}
                - Distance: {distance_int}m ({walk_minutes} min travel)
                - {gradient_line}

                Your sentence MUST include:
                1. The stop name "{stop_name}"
                2. How the route feels in practical terms (short/moderate/long, flat/gentle/steep)
                3. If gradient exceeds 5%: name it as a concern and say it may require assistance or extra effort
                4. If gradient is within 5%: say it is comfortable or straightforward for wheelchair users

                Your sentence MUST NOT include:
                - Any percentages or numbers
                - The words "gradient", "footpath", "AS 1428.1", "walk", or "walking"
                - Use "travel", "travelling", "route", or "path" instead of "walk" or "walking"
                - Generic phrases like "the route is manageable", be specific to this route
                - Any preamble, quotes, or explanation

                Examples of GOOD sentences:
                - "A short, flat route from King St/Lonsdale St with smooth surfaces throughout — comfortable for all wheelchair types."
                - "The path from Spencer St/La Trobe St is brief and mostly level, making it a straightforward approach for wheelchair users."
                - "Travelling from Lonsdale St/Spencer St involves a steep section that may require assistance for manual wheelchair users."

                Write your sentence now:"""

    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=60,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"[Groq ERROR] fallback walk summary: {type(e).__name__}: {e}")
        return None


async def enrich_fallback_stops(
    stops_with_routes: list[dict],
    session: AsyncSession,
) -> list[dict]:
    """Enrich existing fallback stop cards with steepness and LLM summary.

    Takes the stops_with_routes list already built by the existing
    fallback flow (each item has 'stop' and 'walking_route' dicts).
    Adds 'walk_steepness' and 'walk_summary' to each item.

    Steepness queries run concurrently. LLM calls run concurrently
    after steepness is computed (summaries need the gradient value).
    """

    # Step 1: Compute steepness for all walking routes concurrently
    steepness_tasks = []
    for stop_with_route in stops_with_routes:
        walking_leg = stop_with_route.get("walking_route_raw")
        if walking_leg:
            steepness_tasks.append(compute_walk_steepness(walking_leg, session))
        else:
            steepness_tasks.append(_return_none())

    max_gradients = await asyncio.gather(*steepness_tasks)

    # Step 2: Generate LLM summaries concurrently
    summary_tasks = []
    for i, stop_with_route in enumerate(stops_with_routes):
        stop = stop_with_route["stop"]
        walking = stop_with_route["walking_route"]
        summary_tasks.append(
            generate_walk_summary(
                stop_name=stop["name"],
                distance_metres=walking["distance_metres"],
                duration_seconds=walking["duration_seconds"],
                max_gradient=max_gradients[i],
            )
        )

    summaries = await asyncio.gather(*summary_tasks)

    # Step 3: Attach steepness and summary to each stop
    enriched = []
    for i, stop_with_route in enumerate(stops_with_routes):
        grad = max_gradients[i]
        enriched.append({
            "stop": stop_with_route["stop"],
            "walking_route": stop_with_route["walking_route"],
            "walk_steepness": {
                "max_gradient_percent": grad,
                "within_standard": grad <= _AS1428_THRESHOLD if grad is not None else None,
            },
            "walk_summary": summaries[i],
        })

    return enriched


async def _return_none():
    """Async wrapper returning None, used in asyncio.gather."""
    return None