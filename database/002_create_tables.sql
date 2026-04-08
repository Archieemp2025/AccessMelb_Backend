-- Example table to test setup

-- CREATE TABLE IF NOT EXISTS healthcheck (
--     id SERIAL PRIMARY KEY,
--     name TEXT NOT NULL,
--     created_at TIMESTAMP DEFAULT NOW()
-- );

-- DROP TABLE IF EXISTS public_toilet CASCADE;
-- DROP TABLE IF EXISTS destination CASCADE;

CREATE TABLE IF NOT EXISTS destination (
    destination_id SERIAL PRIMARY KEY,
    feature_name VARCHAR(255) NOT NULL,
    theme VARCHAR(100) NOT NULL,
    sub_theme VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,
    location geometry(Point, 4326) NOT NULL
);

CREATE TABLE IF NOT EXISTS public_toilet (
    toilet_id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    wheelchair_accessible VARCHAR(10) NOT NULL DEFAULT 'unknown',
    location geometry(Point, 4326) NOT NULL
);

COMMENT ON TABLE destination IS 'Accessible destinations within the City of Melbourne. Source: CoM landmarks dataset.';
COMMENT ON COLUMN destination.destination_id IS 'Auto-generated primary key.';
COMMENT ON COLUMN destination.feature_name IS 'Name of the destination from the source dataset.';
COMMENT ON COLUMN destination.theme IS 'High-level theme from the raw dataset.';
COMMENT ON COLUMN destination.sub_theme IS 'Sub-theme from the raw dataset.';
COMMENT ON COLUMN destination.category IS 'Mapped UI category such as gallery, library, theatre, or community.';
COMMENT ON COLUMN destination.location IS 'PostGIS Point geometry in WGS84 (SRID 4326).';

COMMENT ON TABLE public_toilet IS 'Public toilet locations within the City of Melbourne LGA. Source: City of Melbourne Open Data (CC BY 4.0).';
COMMENT ON COLUMN public_toilet.toilet_id IS 'Auto-generated primary key.';
COMMENT ON COLUMN public_toilet.name IS 'Toilet name or description from the source dataset.';
COMMENT ON COLUMN public_toilet.wheelchair_accessible IS 'Wheelchair accessibility status: yes, no, or unknown.';
COMMENT ON COLUMN public_toilet.location IS 'PostGIS Point geometry in WGS84 (SRID 4326).';
