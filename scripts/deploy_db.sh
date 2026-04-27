#!/usr/bin/env bash
set -euo pipefail

DB_NAME="${DB_NAME:-accessmelb}"
DB_USER="${DB_USER:-accessmelb_ta22}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"

if [ -z "${DB_PASSWORD:-}" ]; then
  echo "DB_PASSWORD is not set"
  exit 1
fi

export PGPASSWORD="$DB_PASSWORD"

echo "Applying database scripts..."

if [ -f database/001_enable_postgis.sql ]; then
  psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -f database/001_enable_postgis.sql
fi

if [ -f database/002_create_tables.sql ]; then
  psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -f database/002_create_tables.sql
fi

if [ -f database/003_indexes.sql ]; then
  psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -f database/003_indexes.sql
fi

if [ -f database/004_seed_data.sql ]; then
  psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -f database/004_seed_data.sql
fi

if [ -f database/005_add_place_id_column.sql ]; then
  psql -U "$DB_USER" -d "$DB_NAME" -h "$DB_HOST" -p "$DB_PORT" -f database/005_add_place_id_column.sql
fi

echo "Database deployment complete."