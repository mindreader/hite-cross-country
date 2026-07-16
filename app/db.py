"""
Database engine, session factory, and startup helper.

HITE_DB_PATH env var controls the SQLite file location.
Default: ./data/hite.db

All datetimes in the database are stored as **naive local time** in the
America/Kentucky/Louisville timezone.  See docs/ARCHITECTURE.md for the
full timezone convention.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event as sa_event
from sqlalchemy.orm import Session, sessionmaker

DB_PATH: str = os.environ.get("HITE_DB_PATH", "./data/hite.db")


def _engine_url() -> str:
    return f"sqlite:///{DB_PATH}"


def get_engine():
    engine = create_engine(
        _engine_url(),
        connect_args={"check_same_thread": False},
        echo=False,
    )

    # Enable WAL mode for better concurrent read performance
    @sa_event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


# Lazy singletons – initialised on first call
_engine = None
_SessionLocal = None


def engine():
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


def SessionLocal() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=engine(), autoflush=False, expire_on_commit=False)
    return _SessionLocal()


def init_db() -> None:
    """Create tables if they don't exist (no Alembic)."""
    from app.models import Base  # noqa: F811 – imported here to avoid circular deps

    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine())


def get_db():
    """FastAPI dependency – yields a session, closes on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def reset_singletons() -> None:
    """For tests: drop cached engine/session factory so a new DB_PATH takes effect."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
