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
    "dbname":   get_required_env("POSTGRES_DB"),
    "user":     get_required_env("POSTGRES_USER"),
    "password": get_required_env("POSTGRES_PASSWORD"),
    "host":     os.getenv("POSTGRES_HOST", "localhost"),
    "port":     os.getenv("POSTGRES_PORT", "5432"),
}

CSV_PATH = os.getenv("DESTINATION_CSV_PATH", "data/landmarks.csv")

# Raw CSV has 242 landmarks (fire stations, hospitals, schools, etc.)
# Only cultural/community sub-themes are relevant to AccessMelb
CATEGORY_MAP = {
    "Art Gallery/Museum": "gallery",
    "Library": "library",
    "Theatre Live": "theatre",
    "Cinema": "theatre",
    "Aquarium": "community",
    "Public Buildings": "community",
    "Visitor Centre": "community",
    "Function/Conference/Exhibition Centre": "community",
}


def parse_coordinates(raw):
    """Raw CSV stores coordinates as a single string: '-37.809, 144.975'"""
    parts = raw.strip().strip('"').split(",")
    if len(parts) != 2:
        return None, None
    try:
        return float(parts[0].strip()), float(parts[1].strip())
    except ValueError:
        return None, None


def load_destinations():
    if not os.path.exists(CSV_PATH):
        sys.exit(f"CSV not found: {CSV_PATH}")

    with open(CSV_PATH, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print(f"Read {len(rows)} total landmarks from {CSV_PATH}")

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    cur.execute("TRUNCATE TABLE destination RESTART IDENTITY CASCADE;")

    # ST_MakePoint takes longitude first, then latitude
    insert_sql = """
        INSERT INTO destination (feature_name, theme, sub_theme, category, location)
        VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))
    """

    inserted, skipped, filtered_out = 0, 0, 0

    for row in rows:
        sub_theme = row["Sub Theme"].strip()
        category = CATEGORY_MAP.get(sub_theme)

        if not category:
            filtered_out += 1
            continue

        feature_name = row["Feature Name"].strip()
        theme = row["Theme"].strip()
        lat, lon = parse_coordinates(row["Co-ordinates"])

        if lat is None or lon is None:
            print(f"  SKIPPED (bad coordinates): {feature_name}")
            skipped += 1
            continue

        cur.execute(insert_sql, (feature_name, theme, sub_theme, category, lon, lat))
        inserted += 1

    conn.commit()

    cur.execute("SELECT COUNT(*) FROM destination;")
    total = cur.fetchone()[0]

    cur.execute("""
        SELECT category, COUNT(*)
        FROM destination
        GROUP BY category
        ORDER BY category
    """)
    distribution = cur.fetchall()

    print(f"\nInserted: {inserted} | Skipped: {skipped} | Filtered out: {filtered_out} | Total: {total}")
    print("Category distribution:")
    for category, count in distribution:
        print(f"  {category}: {count}")

    cur.close()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    load_destinations()