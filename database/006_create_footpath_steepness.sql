-- Adds footpath_steepness table for Iteration 3 epics:
--   * Destination Terrain Assessment (500m radius query)
--   * Walking Route Steepness (corridor bounding-box query)
--
-- Source: City of Melbourne Footpath Steepness dataset (CC BY 4.0).
-- Records with gradepc > 30 are excluded at load time as data errors
-- (impossible gradient for a pedestrian footpath).
--
-- Assessment standard: AS 1428.1-2009 Section 5.2 — accessible paths of
-- travel must not exceed 1:20 (5% gradient). This is the only threshold
-- applied. Cross-fall (AS 1428.1 Section 5.2, maximum 1:40) cannot be
-- assessed as the dataset does not contain elevation measurements across
-- the width of footpath segments.
--
-- Idempotent: safe to re-run; uses IF NOT EXISTS for table and indexes.

CREATE TABLE IF NOT EXISTS footpath_steepness (
    footpath_steepness_id SERIAL PRIMARY KEY,
    gradient_percent      FLOAT        NOT NULL,
    address               VARCHAR(255),
    lat                   FLOAT        NOT NULL,
    lon                   FLOAT        NOT NULL,
    geom                  geometry(Point, 4326) NOT NULL
);

COMMENT ON TABLE footpath_steepness IS
'Footpath segment running slope measurements within the City of Melbourne LGA.
Source: City of Melbourne Open Data (Footpath Steepness dataset, CC BY 4.0).
Records with gradepc > 30 excluded at load time as data errors.
Assessment standard: AS 1428.1-2009 Section 5.2 (maximum 5% for accessible
paths of travel). Cross-fall is not assessable from this dataset.';

COMMENT ON COLUMN footpath_steepness.gradient_percent IS
'Running slope percentage from the CoM gradepc field (slope along the direction
of travel). Filtered to values <= 30 at load time. Assessed against AS 1428.1
Section 5.2 which specifies a maximum of 5% for accessible paths of travel.
Cross-fall (perpendicular slope) is not available in this dataset.';

COMMENT ON COLUMN footpath_steepness.address IS
'Street address of the footpath segment from the CoM address field.
May be NULL if missing in source data.';

COMMENT ON COLUMN footpath_steepness.lat IS
'Latitude from the CoM geo_point_2d field. Stored alongside geom for direct
read in steepest-section payloads without ST_Y() calls.';

COMMENT ON COLUMN footpath_steepness.lon IS
'Longitude from the CoM geo_point_2d field. Stored alongside geom for direct
read in corridor-query payloads without ST_X() calls.';

COMMENT ON COLUMN footpath_steepness.geom IS
'PostGIS Point geometry in WGS84 (SRID 4326). GIST-indexed for ST_DWithin
radius queries (Epic A) and corridor bounding-box queries (Epic B).';

-- GIST index supports ST_DWithin proximity queries used by:
--   500m radius around a destination
--   corridor bounding-box between walk start and walk end
CREATE INDEX IF NOT EXISTS idx_footpath_steepness_geom
    ON footpath_steepness USING GIST (geom);

-- B-tree indexes on lat/lon support fast bounding-box pre-filters used by
-- the Epic B corridor query before the spatial check.
CREATE INDEX IF NOT EXISTS idx_footpath_steepness_lat
    ON footpath_steepness (lat);

CREATE INDEX IF NOT EXISTS idx_footpath_steepness_lon
    ON footpath_steepness (lon);