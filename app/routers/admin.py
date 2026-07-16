"""
Coach administration routes (all require authentication).

URL ownership:
  /coach/login      – Login form (GET) and login action (POST) — public
  /coach/logout     – Logout action (POST)
  /coach            – Coach dashboard
  /coach/students   – Student management
  /coach/students/new       – Add student form
  /coach/students/{id}/edit – Edit student
  /coach/events     – Event management
  /coach/events/new         – Create event form
  /coach/events/{id}/edit   – Edit event
  /coach/events/{id}/results – Result entry / editing
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import (
    clear_session_cookie,
    create_session_cookie,
    get_current_coach,
    require_coach,
    verify_password,
)
from app.main import templates

router = APIRouter(prefix="/coach", tags=["admin"])


# ── Login / logout (no auth required) ─────────────────────────────────


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    coach = get_current_coach(request)
    if coach:
        return RedirectResponse("/coach", status_code=303)
    return templates.TemplateResponse(request, "admin/login.html", {"error": None})


@router.post("/login")
async def login_action(request: Request, password: str = Form(...)):
    if verify_password(password):
        response = RedirectResponse("/coach", status_code=303)
        create_session_cookie(response)
        return response
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        {"error": "Invalid password. Please try again."},
        status_code=401,
    )


@router.post("/logout")
async def logout(request: Request):
    response = RedirectResponse("/", status_code=303)
    clear_session_cookie(response)
    return response


# ── Protected routes (require_coach dependency) ───────────────────────


@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request, coach: str = Depends(require_coach)):
    """Coach dashboard with quick-links and recent activity."""
    return templates.TemplateResponse(request, "admin/dashboard.html")


@router.get("/students", response_class=HTMLResponse)
async def manage_students(request: Request, coach: str = Depends(require_coach)):
    """Student management list."""
    return templates.TemplateResponse(request, "admin/students.html")


@router.get("/students/new", response_class=HTMLResponse)
async def new_student_form(request: Request, coach: str = Depends(require_coach)):
    """Add-student form."""
    return templates.TemplateResponse(request, "admin/student_form.html")


@router.get("/students/{student_id}/edit", response_class=HTMLResponse)
async def edit_student_form(student_id: int, request: Request, coach: str = Depends(require_coach)):
    """Edit-student form."""
    return templates.TemplateResponse(request, "admin/student_form.html", {"student_id": student_id})


@router.get("/events", response_class=HTMLResponse)
async def manage_events(request: Request, coach: str = Depends(require_coach)):
    """Event management list."""
    return templates.TemplateResponse(request, "admin/events.html")


@router.get("/events/new", response_class=HTMLResponse)
async def new_event_form(request: Request, coach: str = Depends(require_coach)):
    """Create-event form."""
    return templates.TemplateResponse(request, "admin/event_form.html")


@router.get("/events/{event_id}/edit", response_class=HTMLResponse)
async def edit_event_form(event_id: int, request: Request, coach: str = Depends(require_coach)):
    """Edit-event form."""
    return templates.TemplateResponse(request, "admin/event_form.html", {"event_id": event_id})


@router.get("/events/{event_id}/results", response_class=HTMLResponse)
async def result_entry(event_id: int, request: Request, coach: str = Depends(require_coach)):
    """Bulk result entry / editing for an event."""
    return templates.TemplateResponse(request, "admin/result_entry.html", {"event_id": event_id})
