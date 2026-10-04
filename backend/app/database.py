"""PostgreSQL connection and explicit demo schema initialization."""

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from .models import Base, SCHEMA
from .seed import seed_database


def make_engine(database_url: str):
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url[len("postgres://"):]
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        return engine.execution_options(schema_translate_map={SCHEMA: None})
    if url.get_backend_name() != "postgresql":
        raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
    url = url.set(drivername="postgresql+psycopg")
    options = {"pool_pre_ping": True, "connect_args": {"sslmode": "require"}}
    if url.port == 6543:
        # Supabase's transaction pooler cannot retain prepared statements between requests.
        options["poolclass"] = NullPool
        options["connect_args"]["prepare_threshold"] = None
    else:
        options.update(pool_size=1, max_overflow=0)
    return create_engine(url, **options)


def initialize_database(engine) -> None:
    """Create isolated app tables and seed fictional data once. Run as the DB owner."""
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        Base.metadata.create_all(connection)
        if engine.dialect.name == "postgresql":
            connection.execute(text(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC, anon, authenticated"))
            connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM PUBLIC, anon, authenticated"))
            connection.execute(text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {SCHEMA} FROM PUBLIC, anon, authenticated"))
            for table in Base.metadata.sorted_tables:
                connection.execute(text(f"ALTER TABLE {SCHEMA}.{table.name} ENABLE ROW LEVEL SECURITY"))
    with Session(engine) as db:
        seed_database(db)
