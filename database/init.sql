DROP TABLE IF EXISTS public_toilet CASCADE;

--- Create the Public Toilet table based on the ERD Diagram
--- Removed the following columns from the raw csv: female, male, operator, baby_facil, location string.
CREATE TABLE public_toilet (
    toilet_id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    wheelchair_accessible VARCHAR(10) NOT NULL DEFAULT 'unknown',
    location geometry(Point, 4326) NOT NULL
);

--- Create GIST spatial index for fast promixity queries
CREATE INDEX idx_public_toilet_location ON public_toilet USING GIST (location);

--- Create index on wheelchair_accessible for filtered queries
CREATE INDEX idx_public_toilet_wheelchair ON public_toilet (wheelchair_accessible);


COMMENT ON TABLE public_toilet IS 'Public toilet locations within the City of Melbourne LGA. Source: City of Melbourne Open Data (CC BY 4.0).';
COMMENT ON COLUMN public_toilet.toilet_id IS 'Auto-generated primary key.';
COMMENT ON COLUMN public_toilet.name IS 'Toilet name/description from the CoM dataset.';
COMMENT ON COLUMN public_toilet.wheelchair_accessible IS 'Wheelchair accessibility status: yes, no, or unknown. Raw values normalised from yes/no/U/blank.';
COMMENT ON COLUMN public_toilet.location IS 'PostGIS Point geometry (SRID 4326, WGS84). GIST indexed for spatial queries.';
