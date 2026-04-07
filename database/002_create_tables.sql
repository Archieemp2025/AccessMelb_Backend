-- Example table to test setup

CREATE TABLE IF NOT EXISTS healthcheck (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);