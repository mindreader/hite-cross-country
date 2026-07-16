"""
Event and calendar routes.

URL ownership:
  /events           – Event list (past + upcoming)
  /events/{slug}    – Event detail / results page
  /upcoming         – Upcoming events only
  /calendar         – Calendar (month + agenda views)

"Past" definition used throughout this module
----------------------------------------------
An event is considered *past* once its effective-end datetime has passed.
The effective-end is ``end_datetime`` when set, otherwise ``start_datetime``.
This means an in-progress event (started but not yet finished) still appears
in upcoming/calendar views until it ends.  See ``app.util.event_cutoff_dt``.
"""

from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import templates
from app.models import Event, EventStatus, EventType, Result, ResultStatus
from app.util import (
    build_month_grid,
    calendar_day_abbrevs,
    event_cutoff_dt,
    month_name,
    next_month,
    now_local,
    prev_month,
    seconds_to_mmss,
)

router = APIRouter(tags=["events"])

# ── Helpers ────────────────────────────────────────────────────────────

_EVENT_TYPE_VALUES = [e.value for e in EventType]
_EVENT_TYPE_LABELS = {
    "practice": "Practice",
    "race": "Race",
    "team_meeting": "Team Meeting",
    "other": "Other",
}

_STATUS_LABELS = {
    "scheduled": "Scheduled",
    "postponed": "Postponed",
    "cancelled": "Cancelled",
    "completed": "Completed",
}

_RESULT_STATUS_LABELS = {
    "completed": "Completed",
    "did_not_participate": "DNP",
    "did_not_finish": "DNF",
    "excused": "Excused",
    "disqualified": "DQ",
}


def _filter_by_type(events: list, type_val: str) -> list:
    """Filter event list to a specific type value; '' = all."""
    if not type_val or type_val not in _EVENT_TYPE_VALUES:
        return events
    return [e for e in events if e.type.value == type_val]


# ── Routes ─────────────────────────────────────────────────────────────


@router.get("/upcoming", response_class=HTMLResponse)
async def upcoming_events(
    request: Request,
    type: str = "",
    db: Session = Depends(get_db),
):
    """Future events in chronological order, with optional type filter."""
    now = now_local()

    all_events = (
        db.query(Event)
        .order_by(Event.start_datetime.asc())
        .all()
    )

    # Keep events whose effective-end is in the future
    upcoming = [e for e in all_events if event_cutoff_dt(e) > now]
    upcoming = _filter_by_type(upcoming, type)

    return templates.TemplateResponse(
        request,
        "events/upcoming.html",
        {
            "events": upcoming,
            "current_type": type,
            "type_labels": _EVENT_TYPE_LABELS,
            "status_labels": _STATUS_LABELS,
        },
    )


@router.get("/calendar", response_class=HTMLResponse)
async def calendar(
    request: Request,
    y: int = 0,
    m: int = 0,
    view: str = "",
    type: str = "",
    db: Session = Depends(get_db),
):
    """Calendar page: agenda view (default) and month view (?view=month).

    View selection
    --------------
    - ``?view=month``  – month grid (also shown by CSS on wide screens)
    - ``?view=agenda`` or no param – chronological agenda of future events
    - On narrow screens the month grid is hidden by CSS regardless of param.
    """
    now = now_local()

    # Determine target year/month
    if y and m and 1 <= m <= 12 and y >= 2000:
        cal_year, cal_month = y, m
    else:
        cal_year, cal_month = now.year, now.month

    # Resolve view param
    view = view if view in ("month", "agenda") else "agenda"

    # Fetch all events
    all_events = (
        db.query(Event)
        .order_by(Event.start_datetime.asc())
        .all()
    )

    filtered = _filter_by_type(all_events, type)

    # Agenda: future events
    agenda_events = [e for e in filtered if event_cutoff_dt(e) > now]

    # Month grid: all events in that month (past + future)
    month_events = [
        e for e in filtered
        if e.start_datetime.year == cal_year
        and e.start_datetime.month == cal_month
    ]
    cal_grid = build_month_grid(cal_year, cal_month, month_events)
    day_abbrevs = calendar_day_abbrevs()

    prev_y, prev_m = prev_month(cal_year, cal_month)
    next_y, next_m = next_month(cal_year, cal_month)

    return templates.TemplateResponse(
        request,
        "events/calendar.html",
        {
            "view": view,
            "cal_year": cal_year,
            "cal_month": cal_month,
            "cal_month_name": month_name(cal_month),
            "cal_grid": cal_grid,
            "day_abbrevs": day_abbrevs,
            "prev_y": prev_y,
            "prev_m": prev_m,
            "next_y": next_y,
            "next_m": next_m,
            "now_year": now.year,
            "now_month": now.month,
            "now_day": now.day,
            "agenda_events": agenda_events,
            "current_type": type,
            "type_labels": _EVENT_TYPE_LABELS,
            "status_labels": _STATUS_LABELS,
        },
    )


@router.get("/events", response_class=HTMLResponse)
async def event_list(
    request: Request,
    type: str = "",
    distance: str = "",
    db: Session = Depends(get_db),
):
    """All events with upcoming + past sections, filterable by type and distance."""
    now = now_local()

    all_events = (
        db.query(Event)
        .order_by(Event.start_datetime.asc())
        .all()
    )

    # Collect available distances for filter UI
    all_distance_labels = sorted(
        {e.distance_label for e in all_events if e.distance_label}
    )

    # Apply type filter
    filtered = _filter_by_type(all_events, type)

    # Apply distance filter
    if distance:
        filtered = [e for e in filtered if e.distance_label == distance]

    upcoming = [e for e in filtered if event_cutoff_dt(e) > now]
    past = list(reversed([e for e in filtered if event_cutoff_dt(e) <= now]))

    # Result counts per event (for completed events)
    result_counts: dict[int, int] = {}
    for e in filtered:
        if e.status == EventStatus.completed:
            result_counts[e.id] = len(e.results)

    return templates.TemplateResponse(
        request,
        "events/event_list.html",
        {
            "upcoming": upcoming,
            "past": past,
            "result_counts": result_counts,
            "all_distance_labels": all_distance_labels,
            "current_type": type,
            "current_distance": distance,
            "type_labels": _EVENT_TYPE_LABELS,
            "status_labels": _STATUS_LABELS,
        },
    )


@router.get("/events/{slug}", response_class=HTMLResponse)
async def event_detail(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Single event page – upcoming info and/or completed results."""
    event = db.query(Event).filter(Event.slug == slug).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    now = now_local()
    is_future = event_cutoff_dt(event) > now

    # Build results list: completed (sorted fastest first) then non-completed
    completed_results = sorted(
        [r for r in event.results if r.status == ResultStatus.completed and r.time_seconds is not None],
        key=lambda r: r.time_seconds,
    )
    other_results = [
        r for r in event.results
        if not (r.status == ResultStatus.completed and r.time_seconds is not None)
    ]

    # Google Maps search URL when address is present
    maps_url: str | None = None
    if event.street_address:
        import urllib.parse
        query = f"{event.location_name or ''} {event.street_address}".strip()
        maps_url = "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(query)

    return templates.TemplateResponse(
        request,
        "events/event_detail.html",
        {
            "event": event,
            "is_future": is_future,
            "completed_results": completed_results,
            "other_results": other_results,
            "maps_url": maps_url,
            "type_labels": _EVENT_TYPE_LABELS,
            "status_labels": _STATUS_LABELS,
            "result_status_labels": _RESULT_STATUS_LABELS,
            # seconds_to_mmss is passed explicitly so it's available in the
            # template regardless of whether main.py's _setup_jinja_globals()
            # has registered it as a Jinja2 global (e.g. in tests).
            "seconds_to_mmss": seconds_to_mmss,
        },
    )
