from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from reporting.database import database_url


def initialize_database(url):
    """Apply migrations without requiring a hosting-specific startup command."""
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    engine = create_engine(database_url(url), pool_pre_ping=True)
    try:
        with engine.begin() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(text("SELECT pg_advisory_xact_lock(739204615)"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    finally:
        engine.dispose()
