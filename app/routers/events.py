"""
Event and calendar routes.

URL ownership:
  /events           – Event list (past + upcoming)
  /events/{slug}    – Event detail / results page
  /upcoming         – Upcoming events only
  /calendar         – Calendar (month + agenda views)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import templates

router = APIRouter(tags=["events"])


@router.get("/events", response_class=HTMLResponse)
async def event_list(request: Request, db: Session = Depends(get_db)):
    """All events: upcoming + past, filterable."""
    return templates.TemplateResponse(request, "events/event_list.html")


@router.get("/events/{slug}", response_class=HTMLResponse)
async def event_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    """Single event detail page – schedule info and/or results."""
    return templates.TemplateResponse(request, "events/event_detail.html", {"slug": slug})


@router.get("/upcoming", response_class=HTMLResponse)
async def upcoming_events(request: Request, db: Session = Depends(get_db)):
    """Future events in chronological order."""
    return templates.TemplateResponse(request, "events/upcoming.html")


@router.get("/calendar", response_class=HTMLResponse)
async def calendar(request: Request, db: Session = Depends(get_db)):
    """Calendar page: month + agenda views."""
    return templates.TemplateResponse(request, "events/calendar.html")
