"""Google Places API client for fetching venue details.

Calls Google's Place Details (New) API to retrieve current opening hours
and accessibility information for venues. Used by the destination detail
endpoint to enrich the response with live data from Google.

Place IDs come from the database (populated by the one-time enrichment
script). This service handles the live lookup of variable data, opening
hours change, accessibility info gets updated by venue owners.
"""

import logging
from typing import Optional

import httpx

from app.config import GOOGLE_PLACES_API_KEY


logger = logging.getLogger(__name__)

# Place Details (New) endpoint. Place ID goes in the URL path.
PLACE_DETAILS_URL_TEMPLATE = "https://places.googleapis.com/v1/places/{place_id}"

# Fields needed from Google. Field mask is a comma-separated list passed
# in the X-Goog-FieldMask header.
FIELD_MASK = "regularOpeningHours,accessibilityOptions"

# Maximum seconds to wait for Google to respond. If Google is slow or
# unreachable, return null venue_details
REQUEST_TIMEOUT = 5.0


async def fetch_venue_details(place_id: str) -> Optional[dict]:
    """Fetch opening hours and accessibility for a single place.

    Returns a dict with the raw Google response data, or None on any
    failure (network error, API error, missing data). The caller should
    handle None gracefully.
    """
    if not place_id:
        return None

    url = PLACE_DETAILS_URL_TEMPLATE.format(place_id=place_id)

    headers = {
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": FIELD_MASK,
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.warning(f"Google Places HTTP error for place_id={place_id}: {e.response.status_code}")
        logger.warning(f"Response body: {e.response.text}")
        return None
    except httpx.HTTPError as e:
        logger.warning(f"Google Places request failed for place_id={place_id}: {e}")
        return None