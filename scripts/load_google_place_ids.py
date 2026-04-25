"""One-time enrichment script: populates place_id for each destination.

Queries Google Places "Find Place from Text" with each destination's name
and a location bias around its coordinates. Stores the returned place_id
in the destination table for use by the live opening hours service.

To be run once after the destination table is populated. Safe to re-run, only
updates destinations where place_id is null, so already-enriched rows
aren't re-fetched (saves API quota).
"""

import asyncio
import logging
import sys

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import GOOGLE_PLACES_API_KEY
from app.database import async_session
from app.models import Destination


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# Google Places "Find Place from Text" endpoint.
FIND_PLACE_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"

# Bias the search to a small radius around the destination's coordinates.
LOCATION_BIAS_RADIUS_METRES = 200

# Google rate limits
PER_CALL_DELAY_SECONDS = 0.2


async def find_place_id(client: httpx.AsyncClient, name: str, lat: float, lon: float):
    """Look up a Google place_id for a destination using text search with location bias.

    Returns the place_id string on success, or None when no match is found.
    """
    params = {
        "input": name,
        "inputtype": "textquery",
        "fields": "place_id,name,formatted_address",
        # circle:radius@lat,lng — Google's location bias syntax
        "locationbias": f"circle:{LOCATION_BIAS_RADIUS_METRES}@{lat},{lon}",
        "key": GOOGLE_PLACES_API_KEY,
    }

    try:
        response = await client.get(FIND_PLACE_URL, params=params, timeout=10.0)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as e:
        logger.error(f"HTTP error looking up '{name}': {e}")
        return None

    status = data.get("status")
    if status != "OK":
        # Common non-OK statuses: ZERO_RESULTS (no match), REQUEST_DENIED
        # (key issue), OVER_QUERY_LIMIT.
        logger.warning(f"No match for '{name}': status={status}")
        return None

    candidates = data.get("candidates") or []
    if not candidates:
        logger.warning(f"Empty candidates for '{name}'")
        return None

    candidate = candidates[0]
    place_id = candidate.get("place_id")
    matched_name = candidate.get("name", "?")
    matched_address = candidate.get("formatted_address", "?")

    # Log the match details so you can spot-check whether Google found
    # the right venue.
    logger.info(f"  → matched: {matched_name} | {matched_address}")

    return place_id


async def enrich_destinations():
    """Fetch place_id for every destination missing one, and update the database."""
    async with async_session() as session:
        # Only process destinations where place_id is null. This makes the
        # script safe to re-run after fixing partial failures — already-enriched
        # rows are skipped, saving API calls.
        rows = (await session.execute(
            select(Destination.destination_id, Destination.feature_name)
            .where(Destination.place_id.is_(None))
        )).all()

        if not rows:
            logger.info("All destinations already have place_id. Nothing to do.")
            return

        logger.info(f"Enriching {len(rows)} destinations...")

        # We need lat/lon too, but those come from the geometry column.
        # Fetch them in a separate query because GeoAlchemy syntax is verbose.
        from sqlalchemy import func
        coord_rows = (await session.execute(
            select(
                Destination.destination_id,
                Destination.feature_name,
                func.ST_Y(Destination.location).label("lat"),
                func.ST_X(Destination.location).label("lon"),
            ).where(Destination.place_id.is_(None))
        )).all()

        success_count = 0
        failure_count = 0
        failures = []

        async with httpx.AsyncClient() as client:
            for row in coord_rows:
                logger.info(f"[{row.destination_id}] {row.feature_name}")

                place_id = await find_place_id(
                    client,
                    name=row.feature_name,
                    lat=row.lat,
                    lon=row.lon,
                )

                if place_id is None:
                    failure_count += 1
                    failures.append((row.destination_id, row.feature_name))
                    # Be polite even on failures (avoids hammering Google
                    # if there's a transient issue)
                    await asyncio.sleep(PER_CALL_DELAY_SECONDS)
                    continue

                # Update the destination row with the place_id
                await session.execute(
                    update(Destination)
                    .where(Destination.destination_id == row.destination_id)
                    .values(place_id=place_id)
                )
                await session.commit()

                success_count += 1
                await asyncio.sleep(PER_CALL_DELAY_SECONDS)

        # Final summary
        logger.info("=" * 60)
        logger.info(f"Done. Successful: {success_count}, Failed: {failure_count}")
        if failures:
            logger.warning("Destinations without place_id (need manual review):")
            for dest_id, name in failures:
                logger.warning(f"  [{dest_id}] {name}")


if __name__ == "__main__":
    try:
        asyncio.run(enrich_destinations())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(1)