"""
Public-facing routes: home, students, student detail.

URL ownership:
  /              – Home page
  /students      – Student directory (search + alphabetical list)
  /students/{slug} – Individual student results page + progress graph
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.main import templates
from app.models import Event, EventStatus, Result, ResultStatus, Student
from app.util import now_local, seconds_to_mmss

router = APIRouter(tags=["public"])


# ── Helpers ────────────────────────────────────────────────────────────


def _upcoming_events(db: Session, limit: int = 5) -> list[Event]:
    """Return the next *limit* non-cancelled future events ordered by date."""
    now = now_local()
    return (
        db.query(Event)
        .filter(
            Event.start_datetime > now,
            Event.status != EventStatus.cancelled,
        )
        .order_by(Event.start_datetime)
        .limit(limit)
        .all()
    )


def _build_graph_data(results: list[Result]) -> list[dict]:
    """Build the JSON-serialisable graph payload from completed results.

    Only status=completed results with a time are included.
    Sorted chronologically (oldest first) as required for Chart.js X-axis.
    """
    rows = []
    for r in results:
        if r.status != ResultStatus.completed or r.time_seconds is None:
            continue
        evt = r.event
        rows.append(
            {
                "date": evt.start_datetime.strftime("%Y-%m-%d"),
                "date_label": evt.start_datetime.strftime("%b %-d"),
                "time_seconds": r.time_seconds,
                "time_label": seconds_to_mmss(r.time_seconds),
                "event_name": evt.name,
                "event_slug": evt.slug,
                "event_type": evt.type.value,
                "distance": evt.distance,
                "distance_unit": evt.distance_unit.value if evt.distance_unit else None,
                "distance_label": evt.distance_label,
            }
        )
    # Chronological order for graph
    rows.sort(key=lambda x: x["date"])
    return rows


def _most_common_distance(graph_data: list[dict]) -> str | None:
    """Return the distance_label that appears most often, or None."""
    labels = [r["distance_label"] for r in graph_data if r["distance_label"]]
    if not labels:
        return None
    return Counter(labels).most_common(1)[0][0]


def _distinct_distances(graph_data: list[dict]) -> list[str]:
    """Return a de-duplicated ordered list of distance labels present in graph_data."""
    seen: list[str] = []
    for r in graph_data:
        lbl = r["distance_label"]
        if lbl and lbl not in seen:
            seen.append(lbl)
    return seen


# ── Routes ─────────────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    """Home page: intro copy, student search, upcoming-events preview."""
    upcoming = _upcoming_events(db, limit=5)
    return templates.TemplateResponse(
        request,
        "public/home.html",
        {"upcoming": upcoming},
    )


@router.get("/students", response_class=HTMLResponse)
async def student_directory(
    request: Request,
    q: Optional[str] = None,
    grade: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Alphabetical student directory with optional search and grade filter."""
    query = (
        db.query(Student)
        .filter(Student.active == True)  # noqa: E712
        .order_by(Student.last_name, Student.first_name)
    )

    if q:
        term = f"%{q.strip()}%"
        query = query.filter(
            (Student.first_name.ilike(term))
            | (Student.last_name.ilike(term))
            | (Student.display_name.ilike(term))
        )

    if grade is not None:
        query = query.filter(Student.grade == grade)

    students = query.all()

    # Available grade values for the filter drop-down
    grades = (
        db.query(Student.grade)
        .filter(Student.active == True, Student.grade.isnot(None))  # noqa: E712
        .distinct()
        .order_by(Student.grade)
        .all()
    )
    grade_options = [g[0] for g in grades]

    return templates.TemplateResponse(
        request,
        "public/students.html",
        {
            "students": students,
            "q": q or "",
            "grade": grade,
            "grade_options": grade_options,
        },
    )


@router.get("/students/{slug}", response_class=HTMLResponse)
async def student_detail(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Individual student results page with progress graph."""
    student = (
        db.query(Student)
        .filter(Student.slug == slug)
        .first()
    )
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found")

    # Eagerly load event for each result
    results = (
        db.query(Result)
        .filter(Result.student_id == student.id)
        .options(joinedload(Result.event))
        .join(Result.event)
        .order_by(Event.start_datetime.desc())
        .all()
    )

    # Season summary — only completed results count toward times
    completed = [r for r in results if r.status == ResultStatus.completed and r.time_seconds is not None]
    fastest_time = min((r.time_seconds for r in completed), default=None)
    most_recent = results[0] if results else None

    # Graph data (chronological)
    graph_data = _build_graph_data(results)
    graph_data_json = json.dumps(graph_data)

    default_distance = _most_common_distance(graph_data)
    distances = _distinct_distances(graph_data)

    return templates.TemplateResponse(
        request,
        "public/student_detail.html",
        {
            "student": student,
            "results": results,
            "completed_count": len(completed),
            "fastest_time": fastest_time,
            "most_recent": most_recent,
            "graph_data_json": graph_data_json,
            "default_distance": default_distance,
            "distances": distances,
        },
    )
