-- Adds place_id column to destination table for Google Places API integration.
-- The place_id is populated by a one-time enrichment script (scripts/load_google_place_ids.py)
-- and used by the destination detail endpoint to fetch live opening hours and
-- accessibility information from Google Places.
-- Idempotent: safe to re-run; uses IF NOT EXISTS to skip if column already added.

ALTER TABLE destination ADD COLUMN IF NOT EXISTS place_id VARCHAR(255);