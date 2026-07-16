"""
Tests for the coach admin area: auth gates, student CRUD, event management,
result entry, CSRF protection, and validation.
"""

from __future__ import annotations

import urllib.parse
import os
import pytest
from datetime import datetime, timedelta

# ── Helpers ────────────────────────────────────────────────────────────

def _csrf(unused=None) -> str:
    """Return a fresh signed CSRF token for form submission."""
    from app.auth import generate_csrf_token
    return generate_csrf_token()


def _session_cookie(client_unused=None) -> dict:
    """Return cookie dict with a valid coach session cookie."""
    from app.auth import _get_serializer, _SESSION_COOKIE
    token = _get_serializer().dumps({"u": "coach"})
    return {_SESSION_COOKIE: token}


def _urlencode_pairs(pairs) -> bytes:
    """Encode a list of (key, value) tuples as URL-encoded form data."""
    return urllib.parse.urlencode(pairs).encode("utf-8")


async def _post(client, path, pairs, cookies=None):
    """POST form data (list of (key, value) pairs) to path."""
    body = _urlencode_pairs(pairs)
    return await client.post(
        path,
        content=body,
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )

# ── Auth: every /coach route requires login ────────────────────────────


PROTECTED_ROUTES = [
    ("GET", "/coach"),
    ("GET", "/coach/students"),
    ("GET", "/coach/students/new"),
    ("GET", "/coach/events"),
    ("GET", "/coach/events/new"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
async def test_protected_routes_redirect_to_login(client, method, path):
    """Every protected route must redirect unauthenticated requests to /coach/login."""
    if method == "GET":
        r = await client.get(path, follow_redirects=False)
    else:
        r = await client.post(path, follow_redirects=False)
    assert r.status_code == 303, f"{method} {path} should redirect; got {r.status_code}"
    assert "/coach/login" in r.headers.get("location", ""), (
        f"{method} {path} should redirect to login"
    )


@pytest.mark.asyncio
async def test_login_form_renders(client):
    r = await client.get("/coach/login")
    assert r.status_code == 200
    assert "password" in r.text.lower()
    assert "csrf_token" in r.text


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    csrf = _csrf(None)
    r = await client.post(
        "/coach/login",
        data={"password": "wrongpassword", "csrf_token": csrf},
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_dev_password(client):
    csrf = _csrf(None)
    r = await client.post(
        "/coach/login",
        data={"password": "devcoach", "csrf_token": csrf},
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/coach" in r.headers.get("location", "")
    assert "hite_session" in r.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_login_csrf_rejected_without_token(client):
    """POST to /coach/login with no CSRF token must be rejected."""
    r = await client.post(
        "/coach/login",
        data={"password": "devcoach", "csrf_token": ""},
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_login_csrf_rejected_with_bad_token(client):
    r = await client.post(
        "/coach/login",
        data={"password": "devcoach", "csrf_token": "invalid-token"},
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_dashboard_renders_when_logged_in(client):
    cookies = _session_cookie(client)
    r = await client.get("/coach", cookies=cookies)
    assert r.status_code == 200
    assert "Dashboard" in r.text


@pytest.mark.asyncio
async def test_logout_clears_session(client):
    csrf = _csrf(None)
    cookies = _session_cookie(client)
    r = await client.post(
        "/coach/logout",
        data={"csrf_token": csrf},
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 303


# ── Student CRUD ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_student_list_renders(client):
    cookies = _session_cookie(client)
    r = await client.get("/coach/students", cookies=cookies)
    assert r.status_code == 200
    assert "Manage Students" in r.text


@pytest.mark.asyncio
async def test_student_new_form_renders(client):
    cookies = _session_cookie(client)
    r = await client.get("/coach/students/new", cookies=cookies)
    assert r.status_code == 200
    assert "Add Student" in r.text


@pytest.mark.asyncio
async def test_student_create(client):
    """Create a new student and verify redirect."""
    cookies = _session_cookie(client)
    csrf = _csrf(None)
    r = await client.post(
        "/coach/students/new",
        data={
            "first_name": "Alice",
            "last_name": "Tester",
            "display_name": "",
            "grade": "4",
            "active": "on",
            "csrf_token": csrf,
        },
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/coach/students" in r.headers.get("location", "")


@pytest.mark.asyncio
async def test_student_create_validates_required_fields(client):
    """Submitting empty first_name should re-render form with error."""
    cookies = _session_cookie(client)
    csrf = _csrf(None)
    r = await client.post(
        "/coach/students/new",
        data={
            "first_name": "",
            "last_name": "Tester",
            "csrf_token": csrf,
        },
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 422
    assert "First name is required" in r.text


@pytest.mark.asyncio
async def test_student_create_csrf_required(client):
    cookies = _session_cookie(client)
    r = await client.post(
        "/coach/students/new",
        data={
            "first_name": "Bob",
            "last_name": "Tester",
            "csrf_token": "",
        },
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_student_edit_form_renders(client):
    """Create a student then verify edit form renders."""
    from app.db import SessionLocal
    from app.models import Student

    db = SessionLocal()
    student = db.query(Student).filter(Student.last_name == "Tester").first()
    db.close()

    if student is None:
        pytest.skip("No test student found; run create test first or use seeded data")

    cookies = _session_cookie(client)
    r = await client.get(f"/coach/students/{student.id}/edit", cookies=cookies)
    assert r.status_code == 200
    assert "Edit Student" in r.text


@pytest.mark.asyncio
async def test_student_toggle_active(client):
    """Toggle a student's active status."""
    from app.db import SessionLocal
    from app.models import Student

    db = SessionLocal()
    student = db.query(Student).filter(Student.last_name == "Tester").first()
    db.close()

    if student is None:
        pytest.skip("No test student found")

    cookies = _session_cookie(client)
    csrf = _csrf(None)
    original_active = student.active

    r = await client.post(
        f"/coach/students/{student.id}/toggle-active",
        data={"csrf_token": csrf},
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 303

    # Verify it toggled
    db = SessionLocal()
    db.expire_all()
    updated = db.query(Student).filter(Student.id == student.id).first()
    assert updated.active != original_active
    db.close()


@pytest.mark.asyncio
async def test_student_delete_confirm_page(client):
    from app.db import SessionLocal
    from app.models import Student

    db = SessionLocal()
    student = db.query(Student).filter(Student.last_name == "Tester").first()
    db.close()

    if student is None:
        pytest.skip("No test student found")

    cookies = _session_cookie(client)
    r = await client.get(f"/coach/students/{student.id}/delete", cookies=cookies)
    assert r.status_code == 200
    assert "Delete" in r.text


@pytest.mark.asyncio
async def test_student_delete_without_confirm_noop(client):
    """DELETE without confirm=yes should redirect back to confirm page."""
    from app.db import SessionLocal
    from app.models import Student

    db = SessionLocal()
    student = db.query(Student).filter(Student.last_name == "Tester").first()
    db.close()

    if student is None:
        pytest.skip("No test student found")

    cookies = _session_cookie(client)
    csrf = _csrf(None)
    r = await client.post(
        f"/coach/students/{student.id}/delete",
        data={"csrf_token": csrf, "confirm": ""},
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 303

    # Student should still exist
    db = SessionLocal()
    still_there = db.query(Student).filter(Student.id == student.id).first()
    db.close()
    assert still_there is not None


@pytest.mark.asyncio
async def test_student_delete_with_confirm(client):
    """DELETE with confirm=yes should permanently remove the student."""
    from app.db import SessionLocal
    from app.models import Student

    db = SessionLocal()
    student = db.query(Student).filter(Student.last_name == "Tester").first()
    db.close()

    if student is None:
        pytest.skip("No test student found")

    cookies = _session_cookie(client)
    csrf = _csrf(None)
    r = await client.post(
        f"/coach/students/{student.id}/delete",
        data={"csrf_token": csrf, "confirm": "yes"},
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 303

    db = SessionLocal()
    gone = db.query(Student).filter(Student.id == student.id).first()
    db.close()
    assert gone is None


# ── Event CRUD ─────────────────────────────────────────────────────────


def _future_date() -> str:
    return (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")


def _past_date() -> str:
    return (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")


@pytest.mark.asyncio
async def test_event_list_renders(client):
    cookies = _session_cookie(client)
    r = await client.get("/coach/events", cookies=cookies)
    assert r.status_code == 200
    assert "Manage Events" in r.text


@pytest.mark.asyncio
async def test_event_new_form_renders(client):
    cookies = _session_cookie(client)
    r = await client.get("/coach/events/new", cookies=cookies)
    assert r.status_code == 200
    assert "Create Event" in r.text


@pytest.mark.asyncio
async def test_event_create(client):
    cookies = _session_cookie(client)
    csrf = _csrf(None)
    r = await client.post(
        "/coach/events/new",
        data={
            "name": "Test Race",
            "date": _future_date(),
            "start_time": "09:00",
            "end_time": "",
            "type": "race",
            "status": "scheduled",
            "results_expected": "on",
            "distance": "1.5",
            "distance_unit": "miles",
            "location_name": "Test Field",
            "street_address": "",
            "arrival_datetime": "",
            "description": "Test description",
            "internal_notes": "Coach only note",
            "csrf_token": csrf,
        },
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    # Should redirect to results entry (results_expected=True)
    assert r.status_code == 303
    location = r.headers.get("location", "")
    assert "/coach/events" in location or "/results" in location


@pytest.mark.asyncio
async def test_event_create_validation_error(client):
    """Missing required fields should re-render form with errors."""
    cookies = _session_cookie(client)
    csrf = _csrf(None)
    r = await client.post(
        "/coach/events/new",
        data={
            "name": "",  # required
            "date": "",
            "start_time": "",
            "type": "race",
            "status": "scheduled",
            "csrf_token": csrf,
        },
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 422
    assert "Event name is required" in r.text


@pytest.mark.asyncio
async def test_event_create_csrf_required(client):
    cookies = _session_cookie(client)
    r = await client.post(
        "/coach/events/new",
        data={
            "name": "Test",
            "date": _future_date(),
            "start_time": "09:00",
            "type": "race",
            "status": "scheduled",
            "csrf_token": "",
        },
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_event_duplicate_form(client):
    """Duplicate form should pre-fill from the original event."""
    from app.db import SessionLocal
    from app.models import Event

    db = SessionLocal()
    event = db.query(Event).filter(Event.name == "Test Race").first()
    db.close()

    if event is None:
        pytest.skip("No test event found; run create test first")

    cookies = _session_cookie(client)
    r = await client.get(f"/coach/events/{event.id}/duplicate", cookies=cookies)
    assert r.status_code == 200
    assert "Duplicate" in r.text
    assert "Test Race" in r.text  # name is pre-filled


@pytest.mark.asyncio
async def test_event_cancel_confirm_page(client):
    from app.db import SessionLocal
    from app.models import Event

    db = SessionLocal()
    event = db.query(Event).filter(Event.name == "Test Race").first()
    db.close()

    if event is None:
        pytest.skip("No test event found")

    cookies = _session_cookie(client)
    r = await client.get(f"/coach/events/{event.id}/cancel", cookies=cookies)
    assert r.status_code == 200
    assert "Cancel" in r.text


@pytest.mark.asyncio
async def test_event_cancel_action(client):
    from app.db import SessionLocal
    from app.models import Event, EventStatus

    db = SessionLocal()
    event = db.query(Event).filter(Event.name == "Test Race").first()
    db.close()

    if event is None:
        pytest.skip("No test event found")

    cookies = _session_cookie(client)
    csrf = _csrf(None)
    r = await client.post(
        f"/coach/events/{event.id}/cancel",
        data={"csrf_token": csrf, "confirm": "yes"},
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 303

    db = SessionLocal()
    updated = db.query(Event).filter(Event.id == event.id).first()
    db.close()
    assert updated.status == EventStatus.cancelled


@pytest.mark.asyncio
async def test_event_postpone_form_renders(client):
    from app.db import SessionLocal
    from app.models import Event

    db = SessionLocal()
    event = db.query(Event).filter(Event.name == "Test Race").first()
    db.close()

    if event is None:
        pytest.skip("No test event found")

    cookies = _session_cookie(client)
    r = await client.get(f"/coach/events/{event.id}/postpone", cookies=cookies)
    assert r.status_code == 200
    assert "Postpone" in r.text


@pytest.mark.asyncio
async def test_event_postpone_action(client):
    from app.db import SessionLocal
    from app.models import Event, EventStatus

    db = SessionLocal()
    event = db.query(Event).filter(Event.name == "Test Race").first()
    db.close()

    if event is None:
        pytest.skip("No test event found")

    new_date = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")

    cookies = _session_cookie(client)
    csrf = _csrf(None)
    r = await client.post(
        f"/coach/events/{event.id}/postpone",
        data={
            "new_date": new_date,
            "new_start_time": "10:00",
            "csrf_token": csrf,
        },
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 303

    db = SessionLocal()
    updated = db.query(Event).filter(Event.id == event.id).first()
    db.close()
    assert updated.status == EventStatus.postponed


@pytest.mark.asyncio
async def test_event_delete_confirm_page(client):
    from app.db import SessionLocal
    from app.models import Event

    db = SessionLocal()
    event = db.query(Event).filter(Event.name == "Test Race").first()
    db.close()

    if event is None:
        pytest.skip("No test event found")

    cookies = _session_cookie(client)
    r = await client.get(f"/coach/events/{event.id}/delete", cookies=cookies)
    assert r.status_code == 200
    assert "Delete" in r.text


@pytest.mark.asyncio
async def test_event_delete_action(client):
    """Create a separate event and delete it, verifying it's gone."""
    from app.db import SessionLocal
    from app.models import Event

    # Create an event to delete
    cookies = _session_cookie(client)
    csrf = _csrf(None)
    await client.post(
        "/coach/events/new",
        data={
            "name": "Delete Me Event",
            "date": _future_date(),
            "start_time": "08:00",
            "type": "practice",
            "status": "scheduled",
            "results_expected": "",
            "csrf_token": csrf,
        },
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=True,
    )

    db = SessionLocal()
    event = db.query(Event).filter(Event.name == "Delete Me Event").first()
    db.close()

    assert event is not None, "Event should have been created"

    csrf2 = _csrf(None)
    r = await client.post(
        f"/coach/events/{event.id}/delete",
        data={"csrf_token": csrf2, "confirm": "yes"},
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 303

    db = SessionLocal()
    gone = db.query(Event).filter(Event.id == event.id).first()
    db.close()
    assert gone is None


# ── Result entry ───────────────────────────────────────────────────────


def _create_test_event(db, name="Results Test Event", results_expected=True):
    """Helper: create an event and return it."""
    from app.models import Event, EventType, EventStatus
    from app.util import event_slug, unique_slug

    dt = datetime.now() - timedelta(days=5)
    base_slug = event_slug(name, dt)
    slug = unique_slug(base_slug, lambda s: db.query(Event).filter(Event.slug == s).first() is not None)
    event = Event(
        name=name,
        slug=slug,
        start_datetime=dt,
        type=EventType.race,
        status=EventStatus.scheduled,
        results_expected=results_expected,
        distance=1.5,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def _create_test_student(db, first="Zach", last="Testerson"):
    """Helper: create an active student and return it."""
    from app.models import Student
    from app.util import student_slug, unique_slug

    base = student_slug(first, last)
    slug = unique_slug(base, lambda s: db.query(Student).filter(Student.slug == s).first() is not None)
    student = Student(
        first_name=first, last_name=last, slug=slug, active=True
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


@pytest.mark.asyncio
async def test_result_entry_form_renders(client):
    """Result entry form should list active students."""
    from app.db import SessionLocal

    db = SessionLocal()
    event = _create_test_event(db, name="Entry Form Test Event")
    student = _create_test_student(db, first="Zach", last="FormTester")
    db.close()

    cookies = _session_cookie(client)
    r = await client.get(f"/coach/events/{event.id}/results", cookies=cookies)
    assert r.status_code == 200
    assert "Zach" in r.text or "FormTester" in r.text


@pytest.mark.asyncio
async def test_result_entry_requires_auth(client):
    from app.db import SessionLocal

    db = SessionLocal()
    event = _create_test_event(db, name="Auth Guard Test Event")
    db.close()

    r = await client.get(f"/coach/events/{event.id}/results", follow_redirects=False)
    assert r.status_code == 303
    assert "/coach/login" in r.headers.get("location", "")


@pytest.mark.asyncio
async def test_result_entry_happy_path(client):
    """Submit results for active students; blank rows should be skipped."""
    from app.db import SessionLocal
    from app.models import Result

    db = SessionLocal()
    event = _create_test_event(db, name="Happy Path Race")
    student1 = _create_test_student(db, first="HappyA", last="Runner")
    student2 = _create_test_student(db, first="HappyB", last="Runner")
    db.close()

    cookies = _session_cookie(client)
    csrf = _csrf(None)

    # Build form: student1 gets a completed result, student2 gets DNP
    pairs = [
        ("csrf_token", csrf),
        ("confirmed", "0"),
        # student1: completed, 9:00
        ("student_id", str(student1.id)),
        ("minutes", "9"),
        ("seconds", "00"),
        ("status", "completed"),
        ("placement", "1"),
        ("notes", ""),
        # student2: did_not_participate
        ("student_id", str(student2.id)),
        ("minutes", ""),
        ("seconds", ""),
        ("status", "did_not_participate"),
        ("placement", ""),
        ("notes", ""),
    ]
    r = await _post(client, f"/coach/events/{event.id}/results", pairs, cookies=cookies)
    assert r.status_code == 303

    db = SessionLocal()
    r1 = db.query(Result).filter(
        Result.student_id == student1.id, Result.event_id == event.id
    ).first()
    r2 = db.query(Result).filter(
        Result.student_id == student2.id, Result.event_id == event.id
    ).first()
    db.close()

    assert r1 is not None, "Student1 result should have been created"
    assert r1.time_seconds == 540  # 9:00
    assert r1.placement == 1
    assert r2 is not None, "Student2 DNP result should have been created"
    assert r2.time_seconds is None


@pytest.mark.asyncio
async def test_result_entry_blank_rows_skipped(client):
    """Rows with no status set should not create results."""
    from app.db import SessionLocal
    from app.models import Result

    db = SessionLocal()
    event = _create_test_event(db, name="Blank Skip Race")
    student = _create_test_student(db, first="BlankRow", last="Student")
    db.close()

    cookies = _session_cookie(client)
    csrf = _csrf(None)

    pairs = [
        ("csrf_token", csrf),
        ("confirmed", "0"),
        # Blank row: no status
        ("student_id", str(student.id)),
        ("minutes", ""),
        ("seconds", ""),
        ("status", ""),  # blank
        ("placement", ""),
        ("notes", ""),
    ]
    r = await _post(client, f"/coach/events/{event.id}/results", pairs, cookies=cookies)
    assert r.status_code == 303

    db = SessionLocal()
    result = db.query(Result).filter(
        Result.student_id == student.id, Result.event_id == event.id
    ).first()
    db.close()
    assert result is None, "Blank row should not create a result"


@pytest.mark.asyncio
async def test_result_entry_validation_preserves_input(client):
    """Validation errors should re-render form with entered values preserved."""
    from app.db import SessionLocal

    db = SessionLocal()
    event = _create_test_event(db, name="Validation Preserve Race")
    student = _create_test_student(db, first="ValPreserve", last="Student")
    db.close()

    cookies = _session_cookie(client)
    csrf = _csrf(None)

    # Invalid: status=completed but seconds=99
    r = await _post(client, f"/coach/events/{event.id}/results", [
        ("csrf_token", csrf),
        ("confirmed", "0"),
        ("student_id", str(student.id)),
        ("minutes", "9"),
        ("seconds", "99"),      # invalid
        ("status", "completed"),
        ("placement", ""),
        ("notes", ""),
    ], cookies=cookies)
    assert r.status_code == 422
    # Form should contain the entered minutes value
    assert "9" in r.text
    # Error message should be present
    assert "59" in r.text or "Seconds" in r.text


@pytest.mark.asyncio
async def test_result_entry_time_required_for_completed(client):
    """Completed status requires a time; missing time should fail validation."""
    from app.db import SessionLocal

    db = SessionLocal()
    event = _create_test_event(db, name="Time Required Race")
    student = _create_test_student(db, first="TimeReq", last="Student")
    db.close()

    cookies = _session_cookie(client)
    csrf = _csrf(None)

    r = await _post(client, f"/coach/events/{event.id}/results", [
        ("csrf_token", csrf),
        ("confirmed", "0"),
        ("student_id", str(student.id)),
        ("minutes", ""),   # missing
        ("seconds", ""),   # missing
        ("status", "completed"),
        ("placement", ""),
        ("notes", ""),
    ], cookies=cookies)
    assert r.status_code == 422
    assert "required" in r.text.lower() or "Time" in r.text


@pytest.mark.asyncio
async def test_result_entry_duplicate_prevention(client):
    """Submitting duplicate results for the same student+event should handle gracefully."""
    from app.db import SessionLocal
    from app.models import Result, ResultStatus

    db = SessionLocal()
    event = _create_test_event(db, name="Dup Prevention Race")
    student = _create_test_student(db, first="DupPrev", last="Student")

    # Pre-seed a result
    existing = Result(
        student_id=student.id,
        event_id=event.id,
        status=ResultStatus.completed,
        time_seconds=540,
    )
    db.add(existing)
    db.commit()
    db.close()

    # Submitting again should update (not error out) because the route does upsert
    cookies = _session_cookie(client)
    csrf = _csrf(None)
    r = await _post(client, f"/coach/events/{event.id}/results", [
        ("csrf_token", csrf),
        ("confirmed", "0"),
        ("student_id", str(student.id)),
        ("minutes", "10"),
        ("seconds", "00"),
        ("status", "completed"),
        ("placement", ""),
        ("notes", ""),
    ], cookies=cookies)
    assert r.status_code == 303, "Re-submitting for existing result should succeed (upsert)"

    db = SessionLocal()
    updated = db.query(Result).filter(
        Result.student_id == student.id,
        Result.event_id == event.id,
    ).first()
    db.close()
    assert updated.time_seconds == 600  # updated to 10:00


@pytest.mark.asyncio
async def test_result_entry_csrf_required(client):
    from app.db import SessionLocal

    db = SessionLocal()
    event = _create_test_event(db, name="CSRF Result Race")
    student = _create_test_student(db, first="CsrfResult", last="Student")
    db.close()

    cookies = _session_cookie(client)
    r = await _post(client, f"/coach/events/{event.id}/results", [
        ("csrf_token", ""),
        ("confirmed", "0"),
        ("student_id", str(student.id)),
        ("minutes", "9"),
        ("seconds", "00"),
        ("status", "completed"),
        ("placement", ""),
        ("notes", ""),
    ], cookies=cookies)
    assert r.status_code == 403


# ── Individual result edit / delete ────────────────────────────────────


@pytest.mark.asyncio
async def test_result_edit_form_renders(client):
    from app.db import SessionLocal
    from app.models import Result, ResultStatus

    db = SessionLocal()
    event = _create_test_event(db, name="Edit Result Event")
    student = _create_test_student(db, first="EditResult", last="Student")
    result = Result(
        student_id=student.id,
        event_id=event.id,
        status=ResultStatus.completed,
        time_seconds=540,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    result_id = result.id
    db.close()

    cookies = _session_cookie(client)
    r = await client.get(f"/coach/results/{result_id}/edit", cookies=cookies)
    assert r.status_code == 200
    assert "Edit Result" in r.text


@pytest.mark.asyncio
async def test_result_edit_action(client):
    from app.db import SessionLocal
    from app.models import Result, ResultStatus

    db = SessionLocal()
    event = _create_test_event(db, name="Update Result Event")
    student = _create_test_student(db, first="UpdateResult", last="Student")
    result = Result(
        student_id=student.id,
        event_id=event.id,
        status=ResultStatus.completed,
        time_seconds=540,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    result_id = result.id
    db.close()

    cookies = _session_cookie(client)
    csrf = _csrf(None)
    r = await client.post(
        f"/coach/results/{result_id}/edit",
        data={
            "minutes": "10",
            "seconds": "30",
            "status": "completed",
            "placement": "2",
            "notes": "Updated note",
            "csrf_token": csrf,
        },
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 303

    db = SessionLocal()
    updated = db.query(Result).filter(Result.id == result_id).first()
    db.close()
    assert updated.time_seconds == 630  # 10:30
    assert updated.placement == 2
    assert updated.notes == "Updated note"


@pytest.mark.asyncio
async def test_result_delete_confirm_page(client):
    from app.db import SessionLocal
    from app.models import Result, ResultStatus

    db = SessionLocal()
    event = _create_test_event(db, name="Delete Result Event")
    student = _create_test_student(db, first="DeleteResult", last="Student")
    result = Result(
        student_id=student.id,
        event_id=event.id,
        status=ResultStatus.completed,
        time_seconds=480,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    result_id = result.id
    db.close()

    cookies = _session_cookie(client)
    r = await client.get(f"/coach/results/{result_id}/delete", cookies=cookies)
    assert r.status_code == 200
    assert "Delete" in r.text


@pytest.mark.asyncio
async def test_result_delete_action(client):
    from app.db import SessionLocal
    from app.models import Result, ResultStatus

    db = SessionLocal()
    event = _create_test_event(db, name="Final Delete Result Event")
    student = _create_test_student(db, first="FinalDelete", last="Student")
    result = Result(
        student_id=student.id,
        event_id=event.id,
        status=ResultStatus.completed,
        time_seconds=480,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    result_id = result.id
    db.close()

    cookies = _session_cookie(client)
    csrf = _csrf(None)
    r = await client.post(
        f"/coach/results/{result_id}/delete",
        data={"csrf_token": csrf, "confirm": "yes"},
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 303

    db = SessionLocal()
    gone = db.query(Result).filter(Result.id == result_id).first()
    db.close()
    assert gone is None


# ── Additional auth gates for CRUD routes ─────────────────────────────


@pytest.mark.asyncio
async def test_student_edit_requires_auth(client):
    r = await client.get("/coach/students/1/edit", follow_redirects=False)
    assert r.status_code == 303
    assert "/coach/login" in r.headers.get("location", "")


@pytest.mark.asyncio
async def test_event_edit_requires_auth(client):
    r = await client.get("/coach/events/1/edit", follow_redirects=False)
    assert r.status_code == 303
    assert "/coach/login" in r.headers.get("location", "")


@pytest.mark.asyncio
async def test_result_edit_requires_auth(client):
    r = await client.get("/coach/results/1/edit", follow_redirects=False)
    assert r.status_code == 303
    assert "/coach/login" in r.headers.get("location", "")


# ── CSRF guard on all POST routes ─────────────────────────────────────


@pytest.mark.asyncio
async def test_student_update_csrf_required(client):
    from app.db import SessionLocal
    from app.models import Student

    db = SessionLocal()
    student = db.query(Student).first()
    db.close()

    if student is None:
        pytest.skip("No student available")

    cookies = _session_cookie(client)
    r = await client.post(
        f"/coach/students/{student.id}/edit",
        data={"first_name": "X", "last_name": "Y", "csrf_token": "bad"},
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_event_cancel_csrf_required(client):
    from app.db import SessionLocal
    from app.models import Event

    db = SessionLocal()
    event = db.query(Event).first()
    db.close()

    if event is None:
        pytest.skip("No event available")

    cookies = _session_cookie(client)
    r = await client.post(
        f"/coach/events/{event.id}/cancel",
        data={"confirm": "yes", "csrf_token": ""},
        headers={"content-type": "application/x-www-form-urlencoded"},
        cookies=cookies,
        follow_redirects=False,
    )
    assert r.status_code == 403


# ── Util helpers tests ─────────────────────────────────────────────────


def test_unique_slug_no_collision():
    from app.util import unique_slug
    result = unique_slug("foo-2026-01-01", lambda s: False)
    assert result == "foo-2026-01-01"


def test_unique_slug_with_collision():
    from app.util import unique_slug
    taken = {"foo-2026-01-01", "foo-2026-01-01-2"}
    result = unique_slug("foo-2026-01-01", lambda s: s in taken)
    assert result == "foo-2026-01-01-3"


def test_parse_date_time():
    from app.util import parse_date_time
    dt = parse_date_time("2026-08-30", "09:00")
    assert dt is not None
    assert dt.year == 2026
    assert dt.hour == 9
    assert dt.minute == 0


def test_parse_date_time_invalid():
    from app.util import parse_date_time
    assert parse_date_time("", "09:00") is None
    assert parse_date_time("2026-08-30", "") is None
    assert parse_date_time("bad-date", "09:00") is None


def test_format_date():
    from datetime import datetime
    from app.util import format_date
    assert format_date(datetime(2026, 8, 30)) == "2026-08-30"
    assert format_date(None) == ""


def test_format_time_hhmm():
    from datetime import datetime
    from app.util import format_time_hhmm
    assert format_time_hhmm(datetime(2026, 8, 30, 9, 0)) == "09:00"
    assert format_time_hhmm(None) == ""


def test_csrf_token_verify():
    from app.auth import generate_csrf_token, verify_csrf_token
    token = generate_csrf_token()
    assert verify_csrf_token(token) is True
    assert verify_csrf_token("garbage") is False
    assert verify_csrf_token("") is False
