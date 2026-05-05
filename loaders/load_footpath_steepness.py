import json
import os
import sys

from dotenv import load_dotenv
import psycopg2

load_dotenv()

def get_required_env(key):
    value = os.getenv(key)
    if not value:
        sys.exit(f"Missing required env variable: {key}. Check your .env file.")
    return value

DB_CONFIG = {
    "dbname" : get_required_env("DB_NAME"),
    "user": get_required_env("DB_USER"),
    "password": get_required_env("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
}

JSON_PATH = os.getenv("FOOTPATH_STEEPNESS_JSON_PATH", "data/footpath-steepness.json")

# Records with gradepc > 30 are data errors - impossible gradient for a footpath.
MAX_VALID_GRADIENT = 30.0


def is_within_melbourne(lat, lon):
    return -38.5 < lat < -37.0 and 144.0 < lon < 146.0


def load_footpath_steepness():
    if not os.path.exists(JSON_PATH):
        sys.exit(f"JSON not found: {JSON_PATH}")

    with open(JSON_PATH, encoding="utf-8") as f:
        records = json.load(f)

    print(f"Read {len(records)} total records from {JSON_PATH}")

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
 
    cur.execute("TRUNCATE TABLE footpath_steepness RESTART IDENTITY CASCADE;")
 
    insert_sql = """
        INSERT INTO footpath_steepness (gradient_percent, address, lat, lon, geom)
        VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
    """
 
    inserted = 0
    skipped_no_grade = 0
    skipped_bad_coords = 0
    skipped_error_gradient = 0
 
    for record in records:
        gradepc = record.get("gradepc")
 
        if gradepc is None:
            skipped_no_grade += 1
            continue
 
        if gradepc > MAX_VALID_GRADIENT:
            skipped_error_gradient += 1
            continue
 
        geo = record.get("geo_point_2d") or {}
        lat = geo.get("lat")
        lon = geo.get("lon")
 
        if lat is None or lon is None:
            skipped_bad_coords += 1
            continue
 
        if not is_within_melbourne(lat, lon):
            print(f"WARNING (outside Melbourne): {gradepc}% at ({lat}, {lon})")
 
        address = (record.get("address") or "").strip() or None
 
        cur.execute(insert_sql, (gradepc, address, lat, lon, lon, lat))
        inserted += 1
 
    conn.commit()
 
    cur.execute("SELECT COUNT(*) FROM footpath_steepness;")
    total = cur.fetchone()[0]
 
    print(
        f"\nInserted: {inserted} | "
        f"Skipped no gradient: {skipped_no_grade} | "
        f"Skipped bad coords: {skipped_bad_coords} | "
        f"Skipped error gradient (>30): {skipped_error_gradient} | "
        f"Total: {total}"
    )
 
    if total == 0:
        print("No rows inserted - skipping gradient distribution check.")
        cur.close()
        conn.close()
        return
 
    # Verify the loaded data matches the AS 1428.1 / ADA classification expected
    # by Epic A and Epic B. Iteration 3 plan baseline (28,783 valid records):
    # Flat ~57.4%, Gentle ~26.5%, Moderate ~11.5%, Steep ~4.5%.
    cur.execute("""
        SELECT
            SUM(CASE WHEN gradient_percent <  2.5  THEN 1 ELSE 0 END) AS flat,
            SUM(CASE WHEN gradient_percent >= 2.5
                 AND gradient_percent <  5     THEN 1 ELSE 0 END) AS gentle,
            SUM(CASE WHEN gradient_percent >= 5
                 AND gradient_percent <  8.33  THEN 1 ELSE 0 END) AS moderate,
            SUM(CASE WHEN gradient_percent >= 8.33 THEN 1 ELSE 0 END) AS steep
        FROM footpath_steepness
    """)
    flat, gentle, moderate, steep = cur.fetchone()
 
    print("\nGradient distribution (AS 1428.1 / ADA thresholds):")
    print(f"  Flat     (<2.5%):    {flat:>6} ({100 * flat / total:.1f}%)")
    print(f"  Gentle   (2.5-5%):   {gentle:>6} ({100 * gentle / total:.1f}%)")
    print(f"  Moderate (5-8.33%):  {moderate:>6} ({100 * moderate / total:.1f}%)")
    print(f"  Steep    (>8.33%):   {steep:>6} ({100 * steep / total:.1f}%)")
 
    cur.close()
    conn.close()
    print("\nDone.")
 
 
if __name__ == "__main__":
    load_footpath_steepness()
 