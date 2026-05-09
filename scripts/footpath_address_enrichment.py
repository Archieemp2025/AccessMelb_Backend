"""
One-time enrichment script for the City of Melbourne Footpath Steepness dataset.

Reverse geocodes missing addresses for records where:
  - address is null or empty
  - gradepc >= 5.0 (exceeds AS 1428.1 Section 5.2 accessible path standard)

These are the records most likely to appear as the steepest section in the
terrain assessment endpoint, where a specific location improves the usefulness
of the Groq-generated summary.

Uses Nominatim (OpenStreetMap) — free, no API key required.
Rate limited to 1 request per second per Nominatim usage policy.

Estimated runtime: ~30 minutes for 1,758 records.
"""

import json
import os
import time

import requests

INPUT_PATH  = os.getenv("FOOTPATH_STEEPNESS_JSON_PATH",
                        "data/footpath-steepness.json")
OUTPUT_PATH = os.getenv("FOOTPATH_STEEPNESS_ENRICHED_PATH",
                        "data/footpath-steepness-enriched.json")


# Nominatim configuration
# Nominatim usage policy requires:
#   - A descriptive User-Agent identifying your application
#   - Maximum 1 request per second
# https://operations.osmfoundation.org/policies/nominatim/
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_DELAY = 1.1   # seconds between requests — slightly above 1s minimum
HEADERS = {"User-Agent": "AccessMelb/1.0"}

# Only enrich records that exceed AS 1428.1 Section 5.2 (5% maximum).
# Records below 5% don't need addresses — they will never be the
# steepest section shown to the user.
AS1428_PATH_MAX = 5.0

# Maximum gradient filter, matches load_footpath_steepness.py
MAX_VALID_GRADIENT = 30.0


def reverse_geocode(lat: float, lon: float) -> str | None:
    """
    Call Nominatim to get a street-level address for a coordinate pair.

    Returns a plain string like "Spencer Street, Melbourne" or None if
    Nominatim returns no useful result.

    Zoom level 17 targets street-level precision — specific enough to
    identify the road without returning a full postal address.
    """
    try:
        response = requests.get(
            NOMINATIM_URL,
            params={
                "lat":    lat,
                "lon":    lon,
                "format": "json",
                "zoom":   17,
            },
            headers=HEADERS,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        address = data.get("address", {})
        road    = address.get("road", "").strip()
        suburb  = address.get("suburb", "").strip()

        if road and suburb:
            return f"{road}, {suburb}"
        if road:
            return road
        return None

    except Exception as e:
        print(f"  WARNING: Nominatim request failed for ({lat}, {lon}): {e}")
        return None


def enrich_addresses():
    """
    Load the footpath steepness JSON, reverse geocode missing addresses
    for high-gradient records, and write the enriched dataset to a new file.

    The original file is never modified — the output is a separate file
    that can be used as the input to load_footpath_steepness.py.
    """
    if not os.path.exists(INPUT_PATH):
        print(f"ERROR: Input file not found: {INPUT_PATH}")
        return

    print(f"Loading {INPUT_PATH}...")
    with open(INPUT_PATH, encoding="utf-8") as f:
        records = json.load(f)

    print(f"Total records: {len(records)}")

    # Identify records that need enrichment:
    # - gradepc >= AS1428_PATH_MAX (5%) — only records that could appear as
    #   the steepest section in the terrain endpoint
    # - address is null or empty
    # - gradepc <= MAX_VALID_GRADIENT (30%) — exclude data errors
    to_enrich = [
        (i, r) for i, r in enumerate(records)
        if r.get("gradepc") is not None
        and AS1428_PATH_MAX <= r["gradepc"] <= MAX_VALID_GRADIENT
        and not (r.get("address") or "").strip()
        and r.get("geo_point_2d", {}).get("lat")
        and r.get("geo_point_2d", {}).get("lon")
    ]

    print(f"Records to enrich:  {len(to_enrich)}")
    print(f"Records unchanged:  {len(records) - len(to_enrich)}")
    print(f"Estimated runtime:  ~{len(to_enrich) * NOMINATIM_DELAY / 60:.0f} minutes")
    print()

    enriched  = 0
    failed    = 0

    for count, (idx, record) in enumerate(to_enrich, start=1):
        lat = record["geo_point_2d"]["lat"]
        lon = record["geo_point_2d"]["lon"]

        address = reverse_geocode(lat, lon)

        if address:
            records[idx]["address"] = address
            enriched += 1
            print(f"[{count}/{len(to_enrich)}] {record['gradepc']:.1f}%  →  {address}")
        else:
            failed += 1
            print(f"[{count}/{len(to_enrich)}] {record['gradepc']:.1f}%  →  no result")

        # Nominatim rate limit, 1 request per second maximum
        time.sleep(NOMINATIM_DELAY)

        # Save progress every 100 records in case the script is interrupted.
        # This allows you to restart from the saved file rather than from scratch.
        if count % 100 == 0:
            with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False)
            print(f"  Progress saved to {OUTPUT_PATH} ({count}/{len(to_enrich)} done)")

    # Final save
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)

    print()
    print(f"Done.")
    print(f"Enriched:{enriched}")
    print(f"Failed: {failed}")
    print(f"Output:{OUTPUT_PATH}")
    print()
    print(f"Next step: update FOOTPATH_STEEPNESS_JSON_PATH in your .env to point")
    print(f"to {OUTPUT_PATH} and re-run load_footpath_steepness.py.")


if __name__ == "__main__":
    enrich_addresses()