CREATE INDEX IF NOT EXISTS idx_destination_location
ON destination
USING GIST (location);

CREATE INDEX IF NOT EXISTS idx_destination_category
ON destination (category);

CREATE INDEX IF NOT EXISTS idx_public_toilet_location
ON public_toilet
USING GIST (location);

CREATE INDEX IF NOT EXISTS idx_public_toilet_wheelchair
ON public_toilet (wheelchair_accessible);
