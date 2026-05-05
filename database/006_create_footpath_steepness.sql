-- Adds footpath_steepness table for Iteration 3 epics:
--   * Epic A - Destination Terrain Assessment (500m radius grid query)
--   * Epic B - Walking Route Steepness (corridor bounding-box query)
--
-- Source: City of Melbourne Footpath Steepness dataset.
-- Records with gradepc > 30 are excluded at load time as data errors
-- (impossible gradient for a footpath).
--
-- Idempotent: safe to re-run; uses IF NOT EXISTS for both table and indexes.

CREATE TABLE IF NOT EXISTS footpath_steepness (
    footpath_steepness_id SERIAL PRIMARY KEY,
    gradient_percent FLOAT NOT NULL,
    address VARCHAR(255),
    lat FLOAT NOT NULL,
    lon FLOAT NOT NULL,
    geom geometry(Point, 4326) NOT NULL
);

COMMENT ON TABLE footpath_steepness IS 'Footpath segment gradient measurements within the City of Melbourne LGA. Source: City of Melbourne Open Data (Footpath Steepness dataset, CC BY 4.0). Records with gradepc > 30 excluded at load time as data errors.';
COMMENT ON COLUMN footpath_steepness.footpath_steepness_id IS 'Auto-generated primary key.';
COMMENT ON COLUMN footpath_steepness.gradient_percent IS 'Gradient percentage from the CoM gradepc field. Filtered to values <= 30 at load time. Classified per AS 1428.1 (<2.5 flat, 2.5-5 gentle, 5-8.33 moderate, >8.33 steep).';
COMMENT ON COLUMN footpath_steepness.address IS 'Street address of the footpath segment from the CoM address field. May be NULL if missing in source data.';
COMMENT ON COLUMN footpath_steepness.lat IS 'Latitude from the CoM geo_point_2d field. Stored alongside geom for direct read in steepest-section payloads without ST_Y() calls.';
COMMENT ON COLUMN footpath_steepness.lon IS 'Longitude from the CoM geo_point_2d field. Stored alongside geom for direct read in grid-cell payloads without ST_X() calls.';
COMMENT ON COLUMN footpath_steepness.geom IS 'PostGIS Point geometry in WGS84 (SRID 4326). GIST-indexed for ST_DWithin radius and corridor queries.';

-- GIST index supports ST_DWithin proximity queries used by both Epic A
-- (500m radius grid around destinations) and Epic B (corridor bounding box
-- between walk start and walk end).
CREATE INDEX IF NOT EXISTS idx_footpath_steepness_geom
ON footpath_steepness
USING GIST (geom);

-- B-tree indexes on lat/lon support fast bounding-box pre-filters used by
-- the Epic B corridor query before the ST_DWithin spatial check.
CREATE INDEX IF NOT EXISTS idx_footpath_steepness_lat
ON footpath_steepness (lat);

CREATE INDEX IF NOT EXISTS idx_footpath_steepness_lon
ON footpath_steepness (lon);