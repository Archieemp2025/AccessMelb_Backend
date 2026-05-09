import json
import os
import sys

from dotenv import load_dotenv
import psycopg2

load_dotenv()


def get_required_env(key):
    """
    Read a required environment variable and exit with a clear error message
    if it is missing. Used for database credentials that must be present for
    the script to run — there is no sensible default for these values.
    """
    value = os.getenv(key)
    if not value:
        sys.exit(f"Missing required env variable: {key}. Check your .env file.")
    return value


DB_CONFIG = {
    "dbname":   get_required_env("DB_NAME"),
    "user":     get_required_env("DB_USER"),
    "password": get_required_env("DB_PASSWORD"),
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     os.getenv("DB_PORT", "5432"),
}

JSON_PATH = os.getenv("FOOTPATH_STEEPNESS_JSON_PATH", "data/footpath-steepness-enriched.json")

# Records with gradepc > 30 are excluded as data errors.
# A gradient above 30% is impossible for a pedestrian footpath —
# these are surveying anomalies in the City of Melbourne source data.
MAX_VALID_GRADIENT = 30.0

# AS 1428.1-2009 Section 5.2 — the only threshold used for accessibility
# assessment. Accessible paths of travel must not exceed 1:20 (5%).
AS1428_PATH_MAX = 5.0


def is_within_melbourne(lat, lon):
    """
    Sanity check that coordinates fall within a broad Melbourne bounding box.
    Logs a warning for any record outside this range — does not skip it,
    as the CoM dataset should only contain Melbourne footpaths.
    """
    return -38.5 < lat < -37.0 and 144.0 < lon < 146.0


def load_footpath_steepness():
    """
    Load the City of Melbourne Footpath Steepness dataset into the
    footpath_steepness PostGIS table.

    Source: City of Melbourne Open Data Portal (CC BY 4.0).
    Dataset field used: gradepc — running slope percentage along the
    direction of travel. Assessed against AS 1428.1-2009 Section 5.2
    (maximum 5% for accessible paths of travel).

    Filtering applied at load time:
    - Records with no gradepc value are skipped.
    - Records with gradepc > 30 are skipped as data errors.
    - Records with missing coordinates are skipped.

    The script is idempotent, it truncates the table before inserting,
    so it is safe to re-run without creating duplicate records.

    After loading, prints a summary of inserted and skipped records,
    and verifies the gradient distribution against AS 1428.1 Section 5.2.
    """
    if not os.path.exists(JSON_PATH):
        sys.exit(f"JSON not found: {JSON_PATH}")

    with open(JSON_PATH, encoding="utf-8") as f:
        records = json.load(f)

    print(f"Read {len(records)} total records from {JSON_PATH}")

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # Truncate before insert, makes the script safely re-runnable.
    # RESTART IDENTITY resets the primary key sequence.
    cur.execute("TRUNCATE TABLE footpath_steepness RESTART IDENTITY CASCADE;")

    # ST_MakePoint takes longitude first, then latitude.
    # lon is passed twice, once for the lat/lon columns, once for ST_MakePoint.
    insert_sql = """
        INSERT INTO footpath_steepness
            (gradient_percent, address, lat, lon, geom)
        VALUES
            (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
    """

    inserted = 0
    skipped_no_grade = 0
    skipped_bad_coords = 0
    skipped_error_gradient = 0

    for record in records:
        gradepc = record.get("gradepc")

        # Skip records with no gradient data
        if gradepc is None:
            skipped_no_grade += 1
            continue

        # Skip records with impossible gradients — data errors in source
        if gradepc > MAX_VALID_GRADIENT:
            skipped_error_gradient += 1
            continue

        geo = record.get("geo_point_2d") or {}
        lat = geo.get("lat")
        lon = geo.get("lon")

        # Skip records with missing coordinates
        if lat is None or lon is None:
            skipped_bad_coords += 1
            continue

        if not is_within_melbourne(lat, lon):
            print(f"WARNING (outside Melbourne bounds): {gradepc}% at ({lat}, {lon})")

        address = (record.get("address") or "").strip() or None

        # ST_MakePoint(lon, lat), longitude first, latitude second
        cur.execute(insert_sql, (gradepc, address, lat, lon, lon, lat))
        inserted += 1

    conn.commit()

    # Verify total count
    cur.execute("SELECT COUNT(*) FROM footpath_steepness;")
    total = cur.fetchone()[0]

    print(
        f"\nInserted: {inserted}"
        f"\nSkipped, no gradient data: {skipped_no_grade}"
        f"\nSkipped, bad coordinates: {skipped_bad_coords}"
        f"\nSkipped, error gradient (>30%): {skipped_error_gradient}"
        f"\nTotal rows in table: {total}"
    )

    if total == 0:
        print("No rows inserted:skipping verification.")
        cur.close()
        conn.close()
        return

    # Verify distribution against AS 1428.1-2009 Section 5.2 (5% maximum).
    # Only two categories, within and outside the standard.
    # Expected baseline (28,783 valid records):
    #   Within standard (<5%): ~83.9% (flat + gentle from earlier analysis)
    #   Outside standard (>=5%): ~16.1% (moderate + steep from earlier analysis)
    cur.execute("""
        SELECT
            SUM(CASE WHEN gradient_percent <  5.0 THEN 1 ELSE 0 END) AS within_standard,
            SUM(CASE WHEN gradient_percent >= 5.0 THEN 1 ELSE 0 END) AS outside_standard
        FROM footpath_steepness
    """)
    within, outside = cur.fetchone()

    print(
        f"\nGradient distribution — AS 1428.1 Section 5.2 (5% maximum):"
        f"\n  Within standard  (<5%):   {within:>6} ({100 * within / total:.1f}%)"
        f"\n  Outside standard (>=5%):  {outside:>6} ({100 * outside / total:.1f}%)"
    )

    print(
        "\nNote: This dataset measures running slope only (slope along the direction"
        "\nof travel). Cross-fall (slope perpendicular to travel, AS 1428.1 Section"
        "\n5.2 maximum 1:40) cannot be assessed, the dataset does not contain"
        "\nelevation measurements across the width of footpath segments."
    )

    cur.close()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    load_footpath_steepness()