"""
Coach administration routes.

URL ownership:
  /coach/login                       – Login form (GET/POST) — public
  /coach/logout                      – Logout (POST)
  /coach                             – Dashboard
  /coach/students                    – Student list (search)
  /coach/students/new                – Add student
  /coach/students/{id}/edit          – Edit student
  /coach/students/{id}/toggle-active – Toggle active status
  /coach/students/{id}/delete        – Delete student (GET=confirm, POST=execute)
  /coach/events                      – Event list
  /coach/events/new                  – Create event (GET=form, POST=save)
  /coach/events/{id}/edit            – Edit event (GET=form, POST=save)
  /coach/events/{id}/duplicate       – Duplicate event (GET returns prefilled create form)
  /coach/events/{id}/cancel          – Cancel event (GET=confirm, POST=execute)
  /coach/events/{id}/postpone        – Postpone event (GET=form, POST=execute)
  /coach/events/{id}/complete        – Mark completed (POST)
  /coach/events/{id}/delete          – Delete event (GET=confirm, POST=execute)
  /coach/events/{id}/results         – Bulk result entry (GET=form, POST=save)
  /coach/results/{id}/edit           – Edit single result (GET=form, POST=save)
  /coach/results/{id}/delete         – Delete result (GET=confirm, POST=execute)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing import Optional

from app.auth import (
    clear_session_cookie,
    create_session_cookie,
    generate_csrf_token,
    get_current_coach,
    require_coach,
    verify_csrf_token,
    verify_password,
)
from app.db import get_db
from app.main import templates

# ── Ensure Jinja2 globals are available (lifespan may not run in tests) ──
# This is additive-only: setdefault never overwrites values already set
# by main.py's lifespan._setup_jinja_globals().
def _ensure_jinja_globals() -> None:
    from app import util as _util
    env = templates.env
    env.globals.setdefault("seconds_to_mmss", _util.seconds_to_mmss)
    env.globals.setdefault("now_local", _util.now_local)
    env.globals.setdefault("is_upcoming", _util.is_upcoming)
    env.globals.setdefault("is_past", _util.is_past)
    env.filters.setdefault("mmss", _util.seconds_to_mmss)


_ensure_jinja_globals()

from app.models import (
    DistanceUnit,
    Event,
    EventStatus,
    EventType,
    Result,
    ResultStatus,
    Student,
)
from app.util import (
    event_slug,
    format_date,
    format_datetime_local,
    format_time_hhmm,
    minutes_seconds_to_int,
    now_local,
    parse_date_time,
    parse_datetime_local,
    seconds_to_mmss,
    student_slug,
    unique_slug,
)

router = APIRouter(prefix="/coach", tags=["admin"])

# ── Internal helpers ───────────────────────────────────────────────────


def _csrf_check(csrf_token: str) -> None:
    """Raise 403 if the CSRF token is missing or invalid."""
    if not verify_csrf_token(csrf_token):
        raise HTTPException(
            status_code=403,
            detail="Invalid or expired CSRF token. Please go back and try again.",
        )


def _flash_url(base: str, msg: str, msg_type: str = "success") -> str:
    """Append flash-message query params to *base* URL."""
    import urllib.parse
    params = urllib.parse.urlencode({"msg": msg, "msg_type": msg_type})
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{params}"


def _get_flash(request: Request) -> dict:
    """Extract flash message from query params."""
    msg = request.query_params.get("msg", "")
    msg_type = request.query_params.get("msg_type", "success")
    return {"flash_msg": msg, "flash_type": msg_type}


# ── Login / Logout ─────────────────────────────────────────────────────


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if get_current_coach(request):
        return RedirectResponse("/coach", status_code=303)
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        {"error": None, "csrf_token": generate_csrf_token()},
    )


@router.post("/login")
async def login_action(
    request: Request,
    password: str = Form(...),
    csrf_token: str = Form(default=""),
):
    _csrf_check(csrf_token)
    if verify_password(password):
        response = RedirectResponse("/coach", status_code=303)
        create_session_cookie(response)
        return response
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        {
            "error": "Invalid password. Please try again.",
            "csrf_token": generate_csrf_token(),
        },
        status_code=401,
    )


@router.post("/logout")
async def logout(
    request: Request,
    csrf_token: str = Form(default=""),
):
    _csrf_check(csrf_token)
    response = RedirectResponse("/", status_code=303)
    clear_session_cookie(response)
    return response


# ── Dashboard ──────────────────────────────────────────────────────────


@router.get("", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    now = now_local()

    # Next upcoming event
    next_event = (
        db.query(Event)
        .filter(
            Event.start_datetime > now,
            Event.status.not_in([EventStatus.cancelled]),
        )
        .order_by(Event.start_datetime)
        .first()
    )

    # Events awaiting results: past, results_expected=True, no results yet
    awaiting = (
        db.query(Event)
        .filter(
            Event.start_datetime <= now,
            Event.results_expected == True,
            Event.status == EventStatus.scheduled,
        )
        .order_by(Event.start_datetime.desc())
        .all()
    )
    # Filter to those with zero results
    awaiting = [e for e in awaiting if len(e.results) == 0]

    # Recently completed events (status=completed, last 5)
    recent_completed = (
        db.query(Event)
        .filter(Event.status == EventStatus.completed)
        .order_by(Event.start_datetime.desc())
        .limit(5)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "next_event": next_event,
            "awaiting": awaiting,
            "recent_completed": recent_completed,
            "csrf_token": generate_csrf_token(),
            **_get_flash(request),
        },
    )


# ── Student management ─────────────────────────────────────────────────


@router.get("/students", response_class=HTMLResponse)
async def manage_students(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    query = db.query(Student)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (Student.first_name.ilike(like))
            | (Student.last_name.ilike(like))
            | (Student.display_name.ilike(like))
        )
    students = query.order_by(Student.last_name, Student.first_name).all()

    return templates.TemplateResponse(
        request,
        "admin/students.html",
        {
            "students": students,
            "q": q,
            "csrf_token": generate_csrf_token(),
            **_get_flash(request),
        },
    )


@router.get("/students/new", response_class=HTMLResponse)
async def new_student_form(
    request: Request,
    coach: str = Depends(require_coach),
):
    return templates.TemplateResponse(
        request,
        "admin/student_form.html",
        {
            "student": None,
            "errors": [],
            "form": {},
            "csrf_token": generate_csrf_token(),
        },
    )


@router.post("/students/new")
async def create_student(
    request: Request,
    first_name: str = Form(default=""),
    last_name: str = Form(default=""),
    display_name: str = Form(default=""),
    grade: str = Form(default=""),
    active: str = Form(default=""),
    csrf_token: str = Form(default=""),
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    _csrf_check(csrf_token)

    errors = []
    first_name = first_name.strip()
    last_name = last_name.strip()
    display_name_val = display_name.strip() or None

    if not first_name:
        errors.append("First name is required.")
    if not last_name:
        errors.append("Last name is required.")

    grade_val: Optional[int] = None
    if grade.strip():
        try:
            grade_val = int(grade.strip())
            if not (0 <= grade_val <= 12):
                errors.append("Grade must be between 0 and 12.")
        except ValueError:
            errors.append("Grade must be a number.")

    if errors:
        return templates.TemplateResponse(
            request,
            "admin/student_form.html",
            {
                "student": None,
                "errors": errors,
                "form": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "display_name": display_name,
                    "grade": grade,
                    "active": active,
                },
                "csrf_token": generate_csrf_token(),
            },
            status_code=422,
        )

    # Generate unique slug
    base = student_slug(first_name, last_name)
    slug = unique_slug(base, lambda s: db.query(Student).filter(Student.slug == s).first() is not None)

    student = Student(
        first_name=first_name,
        last_name=last_name,
        display_name=display_name_val,
        slug=slug,
        grade=grade_val,
        active=(active == "on"),
    )
    db.add(student)
    db.commit()
    db.refresh(student)

    return RedirectResponse(
        _flash_url("/coach/students", f"Student {student.full_name} added successfully."),
        status_code=303,
    )


@router.get("/students/{student_id}/edit", response_class=HTMLResponse)
async def edit_student_form(
    student_id: int,
    request: Request,
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return templates.TemplateResponse(
        request,
        "admin/student_form.html",
        {
            "student": student,
            "errors": [],
            "form": {
                "first_name": student.first_name,
                "last_name": student.last_name,
                "display_name": student.display_name or "",
                "grade": str(student.grade) if student.grade is not None else "",
                "active": "on" if student.active else "",
            },
            "csrf_token": generate_csrf_token(),
        },
    )


@router.post("/students/{student_id}/edit")
async def update_student(
    student_id: int,
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    display_name: str = Form(default=""),
    grade: str = Form(default=""),
    active: str = Form(default=""),
    csrf_token: str = Form(default=""),
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    _csrf_check(csrf_token)
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    errors = []
    first_name = first_name.strip()
    last_name = last_name.strip()
    display_name_val = display_name.strip() or None

    if not first_name:
        errors.append("First name is required.")
    if not last_name:
        errors.append("Last name is required.")

    grade_val: Optional[int] = None
    if grade.strip():
        try:
            grade_val = int(grade.strip())
            if not (0 <= grade_val <= 12):
                errors.append("Grade must be between 0 and 12.")
        except ValueError:
            errors.append("Grade must be a number.")

    if errors:
        return templates.TemplateResponse(
            request,
            "admin/student_form.html",
            {
                "student": student,
                "errors": errors,
                "form": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "display_name": display_name,
                    "grade": grade,
                    "active": active,
                },
                "csrf_token": generate_csrf_token(),
            },
            status_code=422,
        )

    # Update slug if name changed
    if first_name != student.first_name or last_name != student.last_name:
        base = student_slug(first_name, last_name)
        slug = unique_slug(
            base,
            lambda s: db.query(Student).filter(Student.slug == s, Student.id != student_id).first() is not None,
        )
        student.slug = slug

    student.first_name = first_name
    student.last_name = last_name
    student.display_name = display_name_val
    student.grade = grade_val
    student.active = (active == "on")
    db.commit()

    return RedirectResponse(
        _flash_url("/coach/students", f"Student {student.full_name} updated."),
        status_code=303,
    )


@router.post("/students/{student_id}/toggle-active")
async def toggle_student_active(
    student_id: int,
    request: Request,
    csrf_token: str = Form(default=""),
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    _csrf_check(csrf_token)
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    student.active = not student.active
    db.commit()
    label = "activated" if student.active else "marked inactive"
    return RedirectResponse(
        _flash_url("/coach/students", f"{student.full_name} {label}."),
        status_code=303,
    )


@router.get("/students/{student_id}/delete", response_class=HTMLResponse)
async def confirm_delete_student(
    student_id: int,
    request: Request,
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    result_count = db.query(Result).filter(Result.student_id == student_id).count()
    return templates.TemplateResponse(
        request,
        "admin/student_delete.html",
        {
            "student": student,
            "result_count": result_count,
            "csrf_token": generate_csrf_token(),
        },
    )


@router.post("/students/{student_id}/delete")
async def delete_student(
    student_id: int,
    request: Request,
    csrf_token: str = Form(default=""),
    confirm: str = Form(default=""),
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    _csrf_check(csrf_token)
    if confirm != "yes":
        return RedirectResponse(f"/coach/students/{student_id}/delete", status_code=303)

    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    name = student.full_name
    db.delete(student)
    db.commit()
    return RedirectResponse(
        _flash_url("/coach/students", f"Student {name} deleted."),
        status_code=303,
    )


# ── Event management ───────────────────────────────────────────────────


@router.get("/events", response_class=HTMLResponse)
async def manage_events(
    request: Request,
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    now = now_local()
    upcoming = (
        db.query(Event)
        .filter(Event.start_datetime > now)
        .order_by(Event.start_datetime)
        .all()
    )
    past = (
        db.query(Event)
        .filter(Event.start_datetime <= now)
        .order_by(Event.start_datetime.desc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "admin/events.html",
        {
            "upcoming": upcoming,
            "past": past,
            "csrf_token": generate_csrf_token(),
            **_get_flash(request),
        },
    )


def _event_form_context(
    event=None,
    form: dict | None = None,
    errors: list | None = None,
    duplicate_of=None,
) -> dict:
    """Build context for the event create/edit form."""
    # Pre-fill form from event object if no override provided
    if form is None and event is not None:
        form = {
            "name": event.name,
            "date": format_date(event.start_datetime),
            "start_time": format_time_hhmm(event.start_datetime),
            "end_time": format_time_hhmm(event.end_datetime) if event.end_datetime else "",
            "type": event.type.value,
            "status": event.status.value,
            "results_expected": "on" if event.results_expected else "",
            "distance": str(event.distance) if event.distance is not None else "",
            "distance_unit": event.distance_unit.value if event.distance_unit else "",
            "location_name": event.location_name or "",
            "street_address": event.street_address or "",
            "arrival_datetime": format_datetime_local(event.arrival_datetime),
            "description": event.description or "",
            "internal_notes": event.internal_notes or "",
        }
    if form is None:
        form = {
            "results_expected": "on",
            "status": "scheduled",
            "type": "practice",
        }

    return {
        "event": event,
        "form": form,
        "errors": errors or [],
        "duplicate_of": duplicate_of,
        "event_types": [(t.value, t.value.replace("_", " ").title()) for t in EventType],
        "event_statuses": [(s.value, s.value.title()) for s in EventStatus],
        "distance_units": [(u.value, u.value.title()) for u in DistanceUnit],
        "csrf_token": generate_csrf_token(),
    }


@router.get("/events/new", response_class=HTMLResponse)
async def new_event_form(
    request: Request,
    coach: str = Depends(require_coach),
):
    return templates.TemplateResponse(
        request,
        "admin/event_form.html",
        _event_form_context(),
    )


@router.get("/events/{event_id}/duplicate", response_class=HTMLResponse)
async def duplicate_event_form(
    event_id: int,
    request: Request,
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    # Pre-fill form from the existing event, but don't set the event (new form)
    ctx = _event_form_context(event=None, duplicate_of=event)
    ctx["form"] = {
        "name": event.name + " (copy)",
        "date": "",  # blank date — coach must set new date
        "start_time": format_time_hhmm(event.start_datetime),
        "end_time": format_time_hhmm(event.end_datetime) if event.end_datetime else "",
        "type": event.type.value,
        "status": "scheduled",
        "results_expected": "on" if event.results_expected else "",
        "distance": str(event.distance) if event.distance is not None else "",
        "distance_unit": event.distance_unit.value if event.distance_unit else "",
        "location_name": event.location_name or "",
        "street_address": event.street_address or "",
        "arrival_datetime": "",
        "description": event.description or "",
        "internal_notes": event.internal_notes or "",
    }
    return templates.TemplateResponse(request, "admin/event_form.html", ctx)


def _parse_event_form(form: dict) -> tuple[dict, list]:
    """Parse and validate the event form data.  Returns (cleaned_data, errors)."""
    errors = []
    data: dict = {}

    name = form.get("name", "").strip()
    if not name:
        errors.append("Event name is required.")
    data["name"] = name

    date_str = form.get("date", "").strip()
    start_time_str = form.get("start_time", "").strip()
    if not date_str:
        errors.append("Event date is required.")
    if not start_time_str:
        errors.append("Start time is required.")

    start_dt = parse_date_time(date_str, start_time_str)
    if date_str and start_time_str and start_dt is None:
        errors.append("Invalid date or start time.")
    data["start_datetime"] = start_dt

    end_time_str = form.get("end_time", "").strip()
    if end_time_str:
        end_dt = parse_date_time(date_str, end_time_str)
        if end_dt is None:
            errors.append("Invalid end time.")
        elif start_dt and end_dt <= start_dt:
            errors.append("End time must be after start time.")
        else:
            data["end_datetime"] = end_dt
    else:
        data["end_datetime"] = None

    type_str = form.get("type", "").strip()
    try:
        data["type"] = EventType(type_str) if type_str else None
        if data["type"] is None:
            errors.append("Event type is required.")
    except ValueError:
        errors.append(f"Invalid event type: {type_str!r}")
        data["type"] = None

    status_str = form.get("status", "scheduled").strip()
    try:
        data["status"] = EventStatus(status_str)
    except ValueError:
        data["status"] = EventStatus.scheduled

    data["results_expected"] = form.get("results_expected", "") == "on"

    dist_str = form.get("distance", "").strip()
    if dist_str:
        try:
            dist = float(dist_str)
            if dist <= 0:
                errors.append("Distance must be a positive number.")
            data["distance"] = dist
        except ValueError:
            errors.append("Distance must be a number.")
            data["distance"] = None
    else:
        data["distance"] = None

    dist_unit_str = form.get("distance_unit", "").strip()
    if dist_unit_str:
        try:
            data["distance_unit"] = DistanceUnit(dist_unit_str)
        except ValueError:
            data["distance_unit"] = None
    else:
        data["distance_unit"] = None

    data["location_name"] = form.get("location_name", "").strip() or None
    data["street_address"] = form.get("street_address", "").strip() or None

    arrival_str = form.get("arrival_datetime", "").strip()
    data["arrival_datetime"] = parse_datetime_local(arrival_str)

    data["description"] = form.get("description", "").strip() or None
    data["internal_notes"] = form.get("internal_notes", "").strip() or None

    return data, errors


@router.post("/events/new")
async def create_event(
    request: Request,
    name: str = Form(default=""),
    date: str = Form(default=""),
    start_time: str = Form(default=""),
    end_time: str = Form(default=""),
    type: str = Form(default="practice"),
    status: str = Form(default="scheduled"),
    results_expected: str = Form(default=""),
    distance: str = Form(default=""),
    distance_unit: str = Form(default=""),
    location_name: str = Form(default=""),
    street_address: str = Form(default=""),
    arrival_datetime: str = Form(default=""),
    description: str = Form(default=""),
    internal_notes: str = Form(default=""),
    csrf_token: str = Form(default=""),
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    _csrf_check(csrf_token)
    form_data = dict(
        name=name, date=date, start_time=start_time, end_time=end_time,
        type=type, status=status, results_expected=results_expected,
        distance=distance, distance_unit=distance_unit,
        location_name=location_name, street_address=street_address,
        arrival_datetime=arrival_datetime,
        description=description, internal_notes=internal_notes,
    )
    data, errors = _parse_event_form(form_data)

    if errors:
        ctx = _event_form_context(event=None, form=form_data, errors=errors)
        return templates.TemplateResponse(request, "admin/event_form.html", ctx, status_code=422)

    base = event_slug(data["name"], data["start_datetime"])
    slug = unique_slug(base, lambda s: db.query(Event).filter(Event.slug == s).first() is not None)

    event = Event(slug=slug, **data)
    db.add(event)
    db.commit()
    db.refresh(event)

    target = f"/coach/events/{event.id}/results" if event.results_expected else "/coach/events"
    msg = f"Event '{event.name}' created."
    if event.results_expected:
        msg += " Enter results below."
    return RedirectResponse(_flash_url(target, msg), status_code=303)


@router.get("/events/{event_id}/edit", response_class=HTMLResponse)
async def edit_event_form(
    event_id: int,
    request: Request,
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return templates.TemplateResponse(
        request,
        "admin/event_form.html",
        _event_form_context(event=event),
    )


@router.post("/events/{event_id}/edit")
async def update_event(
    event_id: int,
    request: Request,
    name: str = Form(default=""),
    date: str = Form(default=""),
    start_time: str = Form(default=""),
    end_time: str = Form(default=""),
    type: str = Form(default="practice"),
    status: str = Form(default="scheduled"),
    results_expected: str = Form(default=""),
    distance: str = Form(default=""),
    distance_unit: str = Form(default=""),
    location_name: str = Form(default=""),
    street_address: str = Form(default=""),
    arrival_datetime: str = Form(default=""),
    description: str = Form(default=""),
    internal_notes: str = Form(default=""),
    csrf_token: str = Form(default=""),
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    _csrf_check(csrf_token)
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    form_data = dict(
        name=name, date=date, start_time=start_time, end_time=end_time,
        type=type, status=status, results_expected=results_expected,
        distance=distance, distance_unit=distance_unit,
        location_name=location_name, street_address=street_address,
        arrival_datetime=arrival_datetime,
        description=description, internal_notes=internal_notes,
    )
    data, errors = _parse_event_form(form_data)

    if errors:
        ctx = _event_form_context(event=event, form=form_data, errors=errors)
        return templates.TemplateResponse(request, "admin/event_form.html", ctx, status_code=422)

    # Regenerate slug if name or date changed
    old_slug = event.slug
    new_base = event_slug(data["name"], data["start_datetime"])
    if new_base != old_slug.rsplit("-", 1)[0] if old_slug.count("-") >= 3 else new_base != old_slug:
        slug = unique_slug(
            new_base,
            lambda s: db.query(Event).filter(Event.slug == s, Event.id != event_id).first() is not None,
        )
        event.slug = slug

    for key, val in data.items():
        setattr(event, key, val)
    db.commit()

    return RedirectResponse(
        _flash_url("/coach/events", f"Event '{event.name}' updated."),
        status_code=303,
    )


@router.get("/events/{event_id}/cancel", response_class=HTMLResponse)
async def confirm_cancel_event(
    event_id: int,
    request: Request,
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return templates.TemplateResponse(
        request,
        "admin/event_cancel.html",
        {"event": event, "csrf_token": generate_csrf_token()},
    )


@router.post("/events/{event_id}/cancel")
async def cancel_event(
    event_id: int,
    request: Request,
    csrf_token: str = Form(default=""),
    confirm: str = Form(default=""),
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    _csrf_check(csrf_token)
    if confirm != "yes":
        return RedirectResponse(f"/coach/events/{event_id}/cancel", status_code=303)

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    event.status = EventStatus.cancelled
    db.commit()
    return RedirectResponse(
        _flash_url("/coach/events", f"Event '{event.name}' cancelled."),
        status_code=303,
    )


@router.get("/events/{event_id}/postpone", response_class=HTMLResponse)
async def postpone_event_form(
    event_id: int,
    request: Request,
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return templates.TemplateResponse(
        request,
        "admin/event_postpone.html",
        {
            "event": event,
            "form": {},
            "errors": [],
            "csrf_token": generate_csrf_token(),
        },
    )


@router.post("/events/{event_id}/postpone")
async def postpone_event(
    event_id: int,
    request: Request,
    new_date: str = Form(default=""),
    new_start_time: str = Form(default=""),
    csrf_token: str = Form(default=""),
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    _csrf_check(csrf_token)
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    errors = []
    if not new_date.strip():
        errors.append("New date is required.")
    if not new_start_time.strip():
        errors.append("New start time is required.")

    new_dt = parse_date_time(new_date.strip(), new_start_time.strip())
    if new_date.strip() and new_start_time.strip() and new_dt is None:
        errors.append("Invalid date or time format.")

    if errors:
        return templates.TemplateResponse(
            request,
            "admin/event_postpone.html",
            {
                "event": event,
                "form": {"new_date": new_date, "new_start_time": new_start_time},
                "errors": errors,
                "csrf_token": generate_csrf_token(),
            },
            status_code=422,
        )

    event.start_datetime = new_dt
    event.status = EventStatus.postponed
    db.commit()
    return RedirectResponse(
        _flash_url("/coach/events", f"Event '{event.name}' postponed to {new_date}."),
        status_code=303,
    )


@router.post("/events/{event_id}/complete")
async def complete_event(
    event_id: int,
    request: Request,
    csrf_token: str = Form(default=""),
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    _csrf_check(csrf_token)
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    event.status = EventStatus.completed
    db.commit()

    if event.results_expected:
        return RedirectResponse(
            _flash_url(f"/coach/events/{event_id}/results", f"Event '{event.name}' marked completed. Enter results below."),
            status_code=303,
        )
    return RedirectResponse(
        _flash_url("/coach/events", f"Event '{event.name}' marked completed."),
        status_code=303,
    )


@router.get("/events/{event_id}/delete", response_class=HTMLResponse)
async def confirm_delete_event(
    event_id: int,
    request: Request,
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    result_count = db.query(Result).filter(Result.event_id == event_id).count()
    return templates.TemplateResponse(
        request,
        "admin/event_delete.html",
        {"event": event, "result_count": result_count, "csrf_token": generate_csrf_token()},
    )


@router.post("/events/{event_id}/delete")
async def delete_event(
    event_id: int,
    request: Request,
    csrf_token: str = Form(default=""),
    confirm: str = Form(default=""),
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    _csrf_check(csrf_token)
    if confirm != "yes":
        return RedirectResponse(f"/coach/events/{event_id}/delete", status_code=303)

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    name = event.name
    db.delete(event)
    db.commit()
    return RedirectResponse(
        _flash_url("/coach/events", f"Event '{name}' and all related results deleted."),
        status_code=303,
    )


# ── Result entry ───────────────────────────────────────────────────────


def _build_result_rows(event: Event, students: list, db: Session, overrides: dict | None = None) -> list:
    """Build the rows list for the result entry template.

    Each row is a dict with student + current/submitted values.
    *overrides* maps student_id → submitted form values (for validation-error re-render).
    """
    existing: dict[int, Result] = {r.student_id: r for r in event.results}

    rows = []
    for student in students:
        result = existing.get(student.id)
        override = (overrides or {}).get(student.id, {})

        if override:
            minutes = override.get("minutes", "")
            seconds = override.get("seconds", "")
            row_status = override.get("status", "")
            placement = override.get("placement", "")
            notes = override.get("notes", "")
            error = override.get("error", "")
        elif result:
            total = result.time_seconds or 0
            minutes = str(total // 60) if result.time_seconds is not None else ""
            seconds = f"{total % 60:02d}" if result.time_seconds is not None else ""
            row_status = result.status.value
            placement = str(result.placement) if result.placement is not None else ""
            notes = result.notes or ""
            error = ""
        else:
            minutes = ""
            seconds = ""
            row_status = ""
            placement = ""
            notes = ""
            error = ""

        rows.append({
            "student": student,
            "result": result,
            "minutes": minutes,
            "seconds": seconds,
            "status": row_status,
            "placement": placement,
            "notes": notes,
            "error": error,
        })

    return rows


@router.get("/events/{event_id}/results", response_class=HTMLResponse)
async def result_entry_form(
    event_id: int,
    request: Request,
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    students = (
        db.query(Student)
        .filter(Student.active == True)
        .order_by(Student.last_name, Student.first_name)
        .all()
    )

    rows = _build_result_rows(event, students, db)

    return templates.TemplateResponse(
        request,
        "admin/result_entry.html",
        {
            "event": event,
            "rows": rows,
            "errors": [],
            "warnings": [],
            "csrf_token": generate_csrf_token(),
            "result_statuses": [(s.value, s.value.replace("_", " ").title()) for s in ResultStatus],
            **_get_flash(request),
        },
    )


@router.post("/events/{event_id}/results")
async def save_results(
    event_id: int,
    request: Request,
    student_id: list[str] = Form(default=[]),
    minutes: list[str] = Form(default=[]),
    seconds: list[str] = Form(default=[]),
    status: list[str] = Form(default=[]),
    placement: list[str] = Form(default=[]),
    notes: list[str] = Form(default=[]),
    csrf_token: str = Form(default=""),
    confirmed: str = Form(default=""),
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    _csrf_check(csrf_token)

    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    students = (
        db.query(Student)
        .filter(Student.active == True)
        .order_by(Student.last_name, Student.first_name)
        .all()
    )

    # Build a student lookup map for validation messages
    student_map: dict[int, Student] = {s.id: s for s in students}

    # The form sends parallel arrays indexed by row position.
    # student_id[i] is the student for row i; minutes[i], seconds[i], etc. are that row's data.
    n_rows = len(student_id)
    minutes = list(minutes) + [""] * n_rows
    seconds = list(seconds) + [""] * n_rows
    status = list(status) + [""] * n_rows
    placement = list(placement) + [""] * n_rows
    notes = list(notes) + [""] * n_rows

    # Build override dict for re-rendering on error (keyed by student_id)
    overrides: dict[int, dict] = {}
    for i in range(n_rows):
        sid_str = student_id[i].strip() if i < len(student_id) else ""
        if not sid_str:
            continue
        try:
            sid = int(sid_str)
        except ValueError:
            continue
        overrides[sid] = {
            "minutes": minutes[i],
            "seconds": seconds[i],
            "status": status[i],
            "placement": placement[i],
            "notes": notes[i],
            "error": "",
        }

    errors: list[str] = []
    warnings: list[dict] = []

    # Validate rows
    for i in range(n_rows):
        sid_str = student_id[i].strip() if i < len(student_id) else ""
        if not sid_str:
            continue
        try:
            sid = int(sid_str)
        except ValueError:
            continue

        student = student_map.get(sid)
        if student is None:
            continue  # submitted student_id not in active students — skip

        row_min = minutes[i].strip()
        row_sec = seconds[i].strip()
        row_status = status[i].strip()
        row_placement = placement[i].strip()
        row_notes = notes[i].strip()

        # Blank row: skip (status is empty, no time)
        if not row_status:
            continue

        row_err = []

        try:
            rs = ResultStatus(row_status)
        except ValueError:
            row_err.append(f"Invalid status '{row_status}'.")
            rs = None

        time_secs = None
        if rs == ResultStatus.completed:
            if not row_min and not row_sec:
                row_err.append("Time is required for Completed status.")
            else:
                # Validate minutes
                if not row_min.strip():
                    row_err.append("Minutes are required.")
                else:
                    try:
                        m = int(row_min.strip())
                        if m < 0:
                            row_err.append("Minutes must be non-negative.")
                    except ValueError:
                        row_err.append("Minutes must be a number.")
                        m = None

                # Validate seconds
                if not row_sec.strip():
                    row_err.append("Seconds are required (use 00 if none).")
                else:
                    try:
                        sec = int(row_sec.strip())
                        if not (0 <= sec <= 59):
                            row_err.append("Seconds must be between 00 and 59.")
                            sec = None
                    except ValueError:
                        row_err.append("Seconds must be a number (00–59).")
                        sec = None

                if not row_err:
                    try:
                        time_secs = minutes_seconds_to_int(m, sec)
                    except ValueError as e:
                        row_err.append(str(e))

                    # Unusual time warning (non-blocking, only if no errors)
                    if time_secs is not None and not row_err:
                        if time_secs < 180 or time_secs > 1800:
                            warnings.append({
                                "student_name": student.full_name,
                                "time_str": seconds_to_mmss(time_secs),
                                "student_id": student.id,
                            })

        # Validate placement
        place_val = None
        if row_placement:
            try:
                place_val = int(row_placement)
                if place_val < 1:
                    row_err.append("Placement must be a positive number.")
                    place_val = None
            except ValueError:
                row_err.append("Placement must be a number.")

        if row_err:
            overrides[student.id]["error"] = " ".join(row_err)
            errors.extend([f"{student.full_name}: {e}" for e in row_err])

    # If there are validation errors, re-render
    if errors:
        rows = _build_result_rows(event, students, db, overrides=overrides)
        return templates.TemplateResponse(
            request,
            "admin/result_entry.html",
            {
                "event": event,
                "rows": rows,
                "errors": errors,
                "warnings": [],
                "csrf_token": generate_csrf_token(),
                "result_statuses": [(s.value, s.value.replace("_", " ").title()) for s in ResultStatus],
                "flash_msg": "",
                "flash_type": "error",
            },
            status_code=422,
        )

    # If unusual time warnings and not confirmed, show warning page
    if warnings and confirmed != "1":
        rows = _build_result_rows(event, students, db, overrides=overrides)
        return templates.TemplateResponse(
            request,
            "admin/result_entry.html",
            {
                "event": event,
                "rows": rows,
                "errors": [],
                "warnings": warnings,
                "csrf_token": generate_csrf_token(),
                "result_statuses": [(s.value, s.value.replace("_", " ").title()) for s in ResultStatus],
                "flash_msg": "",
                "flash_type": "warning",
            },
        )

    # Save results
    saved = 0
    skipped = 0
    existing: dict[int, Result] = {r.student_id: r for r in event.results}

    for i in range(n_rows):
        sid_str = student_id[i].strip() if i < len(student_id) else ""
        if not sid_str:
            skipped += 1
            continue
        try:
            sid = int(sid_str)
        except ValueError:
            skipped += 1
            continue

        row_status = status[i].strip()

        # Skip blank rows
        if not row_status:
            skipped += 1
            continue

        try:
            rs = ResultStatus(row_status)
        except ValueError:
            skipped += 1
            continue

        row_min = minutes[i].strip()
        row_sec = seconds[i].strip()
        row_placement_str = placement[i].strip()
        row_notes_str = notes[i].strip() or None

        time_secs = None
        if rs == ResultStatus.completed and row_min and row_sec:
            try:
                time_secs = minutes_seconds_to_int(int(row_min), int(row_sec))
            except (ValueError, TypeError):
                pass

        place_val = None
        if row_placement_str:
            try:
                place_val = int(row_placement_str)
            except ValueError:
                pass

        if sid in existing:
            result = existing[sid]
            result.status = rs
            result.time_seconds = time_secs
            result.placement = place_val
            result.notes = row_notes_str
        else:
            result = Result(
                student_id=sid,
                event_id=event.id,
                status=rs,
                time_seconds=time_secs,
                placement=place_val,
                notes=row_notes_str,
            )
            db.add(result)
        saved += 1

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        rows = _build_result_rows(event, students, db, overrides=overrides)
        return templates.TemplateResponse(
            request,
            "admin/result_entry.html",
            {
                "event": event,
                "rows": rows,
                "errors": ["Duplicate result detected. Each student can only have one result per event."],
                "warnings": [],
                "csrf_token": generate_csrf_token(),
                "result_statuses": [(s.value, s.value.replace("_", " ").title()) for s in ResultStatus],
                "flash_msg": "",
                "flash_type": "error",
            },
            status_code=422,
        )

    return RedirectResponse(
        _flash_url(
            f"/coach/events/{event_id}/results",
            f"Results saved: {saved} student(s) updated, {skipped} skipped.",
        ),
        status_code=303,
    )


# ── Individual result edit / delete ────────────────────────────────────


@router.get("/results/{result_id}/edit", response_class=HTMLResponse)
async def edit_result_form(
    result_id: int,
    request: Request,
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    result = db.query(Result).filter(Result.id == result_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    total = result.time_seconds or 0
    form = {
        "minutes": str(total // 60) if result.time_seconds is not None else "",
        "seconds": f"{total % 60:02d}" if result.time_seconds is not None else "",
        "status": result.status.value,
        "placement": str(result.placement) if result.placement is not None else "",
        "notes": result.notes or "",
    }

    return templates.TemplateResponse(
        request,
        "admin/result_edit.html",
        {
            "result": result,
            "form": form,
            "errors": [],
            "result_statuses": [(s.value, s.value.replace("_", " ").title()) for s in ResultStatus],
            "csrf_token": generate_csrf_token(),
        },
    )


@router.post("/results/{result_id}/edit")
async def update_result(
    result_id: int,
    request: Request,
    minutes: str = Form(default=""),
    seconds: str = Form(default=""),
    status: str = Form(...),
    placement: str = Form(default=""),
    notes: str = Form(default=""),
    csrf_token: str = Form(default=""),
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    _csrf_check(csrf_token)
    result = db.query(Result).filter(Result.id == result_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    errors = []
    form_data = {"minutes": minutes, "seconds": seconds, "status": status,
                 "placement": placement, "notes": notes}

    try:
        rs = ResultStatus(status.strip())
    except ValueError:
        errors.append("Invalid status.")
        rs = result.status

    time_secs = None
    if rs == ResultStatus.completed:
        if not minutes.strip():
            errors.append("Minutes are required for Completed status.")
        else:
            try:
                m = int(minutes.strip())
            except ValueError:
                errors.append("Minutes must be a number.")
                m = None

        if not seconds.strip():
            errors.append("Seconds are required (use 00 if none).")
        else:
            try:
                sec = int(seconds.strip())
                if not (0 <= sec <= 59):
                    errors.append("Seconds must be 00–59.")
                    sec = None
            except ValueError:
                errors.append("Seconds must be a number (00–59).")
                sec = None

        if not errors:
            try:
                time_secs = minutes_seconds_to_int(m, sec)
            except (ValueError, UnboundLocalError):
                errors.append("Invalid time.")

    place_val = None
    if placement.strip():
        try:
            place_val = int(placement.strip())
            if place_val < 1:
                errors.append("Placement must be a positive number.")
                place_val = None
        except ValueError:
            errors.append("Placement must be a number.")

    if errors:
        return templates.TemplateResponse(
            request,
            "admin/result_edit.html",
            {
                "result": result,
                "form": form_data,
                "errors": errors,
                "result_statuses": [(s.value, s.value.replace("_", " ").title()) for s in ResultStatus],
                "csrf_token": generate_csrf_token(),
            },
            status_code=422,
        )

    result.status = rs
    result.time_seconds = time_secs
    result.placement = place_val
    result.notes = notes.strip() or None
    db.commit()

    return RedirectResponse(
        _flash_url(
            f"/coach/events/{result.event_id}/results",
            f"Result for {result.student.full_name} updated.",
        ),
        status_code=303,
    )


@router.get("/results/{result_id}/delete", response_class=HTMLResponse)
async def confirm_delete_result(
    result_id: int,
    request: Request,
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    result = db.query(Result).filter(Result.id == result_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    return templates.TemplateResponse(
        request,
        "admin/result_delete.html",
        {"result": result, "csrf_token": generate_csrf_token()},
    )


@router.post("/results/{result_id}/delete")
async def delete_result(
    result_id: int,
    request: Request,
    csrf_token: str = Form(default=""),
    confirm: str = Form(default=""),
    db: Session = Depends(get_db),
    coach: str = Depends(require_coach),
):
    _csrf_check(csrf_token)
    if confirm != "yes":
        return RedirectResponse(f"/coach/results/{result_id}/delete", status_code=303)

    result = db.query(Result).filter(Result.id == result_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    event_id = result.event_id
    student_name = result.student.full_name
    db.delete(result)
    db.commit()
    return RedirectResponse(
        _flash_url(
            f"/coach/events/{event_id}/results",
            f"Result for {student_name} deleted.",
        ),
        status_code=303,
    )
