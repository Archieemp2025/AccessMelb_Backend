"""Transformers between Google Places API responses and our schema.

Google returns camelCase, deeply-nested data with various optional fields.
This code flattens and normalise these into a clean snake_case shape for the
frontend.
"""

from typing import Optional


def transform_venue_details(google_response: dict) -> dict:
    """Convert Google's Place Details response to our VenueDetails schema shape.

    Handles missing fields gracefully as venues might not have opening hours
    or any accessibility data, in which case those sections are None.
    """
    return {
        "opening_hours": _transform_opening_hours(google_response.get("regularOpeningHours")),
        "accessibility": _transform_accessibility(google_response.get("accessibilityOptions")),
    }


def _transform_opening_hours(hours_data: Optional[dict]) -> Optional[dict]:
    """Extract the opening hours fields the frontend needs.

    Google returns:
      - openNow: bool (is the venue open right now)
      - weekdayDescriptions: list[str](e.g. "Monday: 10:00 AM – 5:00 PM")
      - periods: list[dict] (machine-readable open/close times)
    """
    if not hours_data:
        return None

    return {
        "open_now": hours_data.get("openNow"),
        "weekday_text": hours_data.get("weekdayDescriptions") or [],
    }


def _transform_accessibility(accessibility_data: Optional[dict]) -> Optional[dict]:
    """Extract the accessibility fields the frontend needs.

    Google returns up to four boolean fields in accessibilityOptions:
      - wheelchairAccessibleEntrance
      - wheelchairAccessibleParking
      - wheelchairAccessibleRestroom
      - wheelchairAccessibleSeating

    Each can be True, False, or absent (meaning Google has no data for it).
    """
    if not accessibility_data:
        return None

    return {
        "wheelchair_entrance": accessibility_data.get("wheelchairAccessibleEntrance"),
        "wheelchair_parking": accessibility_data.get("wheelchairAccessibleParking"),
        "wheelchair_restroom": accessibility_data.get("wheelchairAccessibleRestroom"),
        "wheelchair_seating": accessibility_data.get("wheelchairAccessibleSeating"),
    }