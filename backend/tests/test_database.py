from sqlalchemy.pool import NullPool

from app.database import make_engine
from app.models import Base


def test_postgres_transaction_pooler_disables_client_pool_and_uses_private_schema():
    engine = make_engine("postgresql://postgres.project:password@pooler.example.com:6543/postgres")
    try:
        assert engine.dialect.name == "postgresql"
        assert isinstance(engine.pool, NullPool)
        assert Base.metadata.schema == "verisight"
    finally:
        engine.dispose()
