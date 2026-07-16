"""
Pytest fixtures shared across test modules.
"""

import os
import tempfile
from pathlib import Path

import pytest

# Point DB at a temp file BEFORE any app import
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["HITE_DB_PATH"] = _tmp.name
os.environ["HITE_SESSION_SECRET"] = "test-secret-not-for-prod"
os.environ["HITE_SNAPSHOT_INTERVAL_SECS"] = "0"  # disable backup worker during tests


@pytest.fixture(scope="session")
def app():
    """Create the FastAPI app with a fresh temp database."""
    from app.db import reset_singletons, init_db
    reset_singletons()
    init_db()

    from app.main import create_app
    application = create_app()
    yield application

    # Cleanup
    Path(_tmp.name).unlink(missing_ok=True)


@pytest.fixture(scope="session")
async def client(app):
    """httpx AsyncClient for the ASGI app."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
