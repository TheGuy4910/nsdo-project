"""
Database engine and session management.

DATABASE_URL defaults to the Postgres target in docker-compose.yml. Override
via environment variable for any other setup (local Postgres install, CI, etc).

This module is written against SQLAlchemy 2.0 but cannot be executed in the
sandbox used to author it (no network access to install sqlalchemy/psycopg2).
It has been reviewed for correctness but not run. See docs/PHASE_2_NOTES.md
for exactly what was and was not verified.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://nsdo:nsdo_dev_password@localhost:5432/nsdo",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency: yields a session, always closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
