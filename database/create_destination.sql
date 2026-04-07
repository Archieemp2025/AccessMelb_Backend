CREATE EXTENSION IF NOT EXISTS postgis;
 
DROP TABLE IF EXISTS destination CASCADE;
 
CREATE TABLE destination (
    destination_id SERIAL PRIMARY KEY,
    feature_name VARCHAR(255) NOT NULL,
    theme VARCHAR(100) NOT NULL,
    sub_theme VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL,  -- maps to UI filter: gallery, library, theatre, community
    location  geometry(Point, 4326) NOT NULL
);
 
-- GIST index enables fast ST_DWithin() proximity queries against this table
CREATE INDEX idx_destination_location ON destination USING GIST (location);
 
-- supports filtering by UI category buttons without full table scan
CREATE INDEX idx_destination_category ON destination (category);