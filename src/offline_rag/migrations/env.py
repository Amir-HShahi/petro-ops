"""Runs the migrations against `DATABASE_URL`, or the URL a caller put in the Alembic config."""

from alembic import context
from sqlalchemy import create_engine

from offline_rag.settings import Settings

# Tests pass their own schema-scoped URL; everyone else uses the configured one.
database_url: str = context.config.attributes.get("database_url") or Settings().database_url

# SQLAlchemy needs the driver named in the scheme; libpq and psycopg do not.
engine = create_engine(database_url.replace("postgresql://", "postgresql+psycopg://", 1))
with engine.connect() as connection:
    context.configure(connection=connection, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
