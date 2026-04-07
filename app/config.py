import os
import sys

from dotenv import load_dotenv

load_dotenv()


def get_required_env(key):
    value = os.getenv(key)
    if not value:
        sys.exit(f"Missing required env variable: {key}. Check your .env file.")
    return value


POSTGRES_DB = get_required_env("POSTGRES_DB")
POSTGRES_USER = get_required_env("POSTGRES_USER")
POSTGRES_PASSWORD = get_required_env("POSTGRES_PASSWORD")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

# asyncpg requires the +asyncpg dialect in the URL
DATABASE_URL = (
    f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)