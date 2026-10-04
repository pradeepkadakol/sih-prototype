"""Initialize the app's schema and fictional demo records once."""

import os
from pathlib import Path

from dotenv import load_dotenv

from .database import initialize_database, make_engine


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgres://", "postgresql+psycopg://")):
        raise SystemExit("Set DATABASE_URL to your Supabase PostgreSQL URL in the root .env file")
    engine = make_engine(database_url)
    try:
        initialize_database(engine)
    finally:
        engine.dispose()
    print("VeriSight PostgreSQL schema and demo records are ready.")


if __name__ == "__main__":
    main()
