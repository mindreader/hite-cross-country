"""
FastAPI application factory for Hite Elementary Cross Country.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import db, auth, util

log = logging.getLogger("hite")

# ── Paths ──────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

# ── Jinja2 globals (available in every template) ───────────────────────

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

def _setup_jinja_globals():
    """Register helpers and filters that all templates can use."""
    env = templates.env
    env.globals["seconds_to_mmss"] = util.seconds_to_mmss
    env.globals["now_local"] = util.now_local
    env.globals["is_upcoming"] = util.is_upcoming
    env.globals["is_past"] = util.is_past
    env.filters["mmss"] = util.seconds_to_mmss


# ── Lifespan ───────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
    log.info("Starting Hite XC …")
    db.init_db()
    auth.init_auth()
    _setup_jinja_globals()
    yield
    log.info("Shutting down Hite XC.")


# ── App factory ────────────────────────────────────────────────────────


def create_app() -> FastAPI:
    app = FastAPI(
        title="Hite Elementary Cross Country",
        lifespan=lifespan,
        docs_url=None,     # No Swagger UI in prod
        redoc_url=None,
    )

    # ── Middleware: X-Robots-Tag on every response ─────────────────
    @app.middleware("http")
    async def robots_noindex(request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    # ── Static files ──────────────────────────────────────────────
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # ── Healthcheck (before routers so it's always reachable) ─────
    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return JSONResponse({"status": "ok"})

    # ── Routers ──────────────────────────────────────────────────
    from app.routers import public, events, admin  # noqa: E402

    app.include_router(public.router)
    app.include_router(events.router)
    app.include_router(admin.router)

    return app


# For ``uvicorn app.main:app``
app = create_app()
