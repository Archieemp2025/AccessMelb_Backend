import csv
import sys
import os

from dotenv import load_dotenv
import psycopg2

load_dotenv()


def get_required_env(key):
    value = os.getenv(key)
    if not value:
        sys.exit(f"Missing required env variable: {key}. Check your .env file.")
    return value


DB_CONFIG = {
    "dbname": get_required_env("DB_NAME"),
    "user": get_required_env("DB_USER"),
    "password": get_required_env("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
}

CSV_PATH = os.getenv("TOILET_CSV_PATH", "data/public-toilets.csv")


def normalise_wheelchair(raw_value):
    val = raw_value.strip().lower()
    if val == "yes":
        return "yes"
    if val == "no":
        return "no"
    return "unknown"


def is_within_melbourne(lat, lon):
    return -38.5 < lat < -37.0 and 144.0 < lon < 146.0


def load_toilets():
    if not os.path.exists(CSV_PATH):
        sys.exit(f"CSV not found: {CSV_PATH}")

    with open(CSV_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print(f"Read {len(rows)} toilets from {CSV_PATH}")

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    cur.execute("TRUNCATE TABLE public_toilet RESTART IDENTITY CASCADE;")

    insert_sql = """
        INSERT INTO public_toilet (name, wheelchair_accessible, location)
        VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
    """

    inserted, skipped = 0, 0

    for row in rows:
        name = row["name"].strip()
        wheelchair = normalise_wheelchair(row.get("wheelchair", ""))
        raw_lat = row.get("lat", "").strip()
        raw_lon = row.get("lon", "").strip()

        if not raw_lat or not raw_lon:
            print(f"SKIPPED (no coordinates): {name}")
            skipped += 1
            continue

        try:
            lat, lon = float(raw_lat), float(raw_lon)
        except ValueError:
            print(f"SKIPPED (invalid coordinates): {name}")
            skipped += 1
            continue

        if not is_within_melbourne(lat, lon):
            print(f"WARNING (outside Melbourne): {name} ({lat}, {lon})")

        cur.execute(insert_sql, (name, wheelchair, lon, lat))
        inserted += 1

    conn.commit()

    cur.execute("SELECT COUNT(*) FROM public_toilet;")
    total = cur.fetchone()[0]

    cur.execute("""
        SELECT wheelchair_accessible, COUNT(*)
        FROM public_toilet
        GROUP BY wheelchair_accessible
        ORDER BY wheelchair_accessible
    """)
    distribution = cur.fetchall()

    print(f"\nInserted: {inserted} | Skipped: {skipped} | Total: {total}")
    print("Wheelchair distribution:")
    for status, count in distribution:
        print(f"  {status}: {count}")

    cur.close()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    load_toilets()
