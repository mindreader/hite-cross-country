#!/usr/bin/env python3
"""
Seed script for Hite Elementary Cross Country.

Creates sample students, events, and results per PRD section 16.
Idempotent: refuses to run on a non-empty database unless --force is passed.

Usage:
  python scripts/seed.py          # safe — exits if data exists
  python scripts/seed.py --force  # wipes and re-seeds
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Allow running from repo root: ``python scripts/seed.py``
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal, init_db, engine  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    DistanceUnit,
    Event,
    EventStatus,
    EventType,
    Result,
    ResultStatus,
    Student,
)
from app.util import event_slug, now_local, student_slug  # noqa: E402


def db_has_data(session) -> bool:
    return session.query(Student).first() is not None


def seed(session) -> None:
    now = now_local()

    # ── Students (at least 6) ────────────────────────────────────────
    students_data = [
        ("Robert", "Watson", 4),
        ("Jane", "Smith", 5),
        ("Alex", "Jones", 3),
        ("Maria", "Garcia", 4),
        ("Ethan", "Brown", 5),
        ("Lily", "Chen", 3),
        ("Sam", "Davis", 4),
        ("Olivia", "Taylor", 5),
    ]

    students = []
    for first, last, grade in students_data:
        s = Student(
            first_name=first,
            last_name=last,
            slug=student_slug(first, last),
            grade=grade,
            active=True,
        )
        session.add(s)
        students.append(s)

    session.flush()  # get IDs

    # ── Events ───────────────────────────────────────────────────────

    # Past practices (1-mile)
    practice_dates = [
        now - timedelta(days=28),
        now - timedelta(days=21),
        now - timedelta(days=14),
        now - timedelta(days=7),
    ]

    practices = []
    for i, dt in enumerate(practice_dates, 1):
        evt_dt = dt.replace(hour=15, minute=30, second=0, microsecond=0)
        evt = Event(
            name=f"Timed Mile #{i}",
            slug=event_slug(f"Timed Mile {i}", evt_dt),
            start_datetime=evt_dt,
            end_datetime=evt_dt.replace(hour=16, minute=30),
            type=EventType.practice,
            status=EventStatus.completed,
            results_expected=True,
            distance=1.0,
            distance_unit=DistanceUnit.miles,
            location_name="Hite Elementary Field",
            description="Weekly timed mile practice.",
        )
        session.add(evt)
        practices.append(evt)

    # Past races (various distances)
    race1_dt = (now - timedelta(days=18)).replace(hour=9, minute=0, second=0, microsecond=0)
    race1 = Event(
        name="Hite Invitational",
        slug=event_slug("Hite Invitational", race1_dt),
        start_datetime=race1_dt,
        end_datetime=race1_dt.replace(hour=11, minute=0),
        type=EventType.race,
        status=EventStatus.completed,
        results_expected=True,
        distance=1.0,
        distance_unit=DistanceUnit.miles,
        location_name="Hite Elementary",
        street_address="3023 Breckenridge Lane, Louisville, KY 40220",
        arrival_datetime=race1_dt - timedelta(hours=1),
        description="Annual Hite Invitational race. Arrive by 8:00 AM.",
    )
    session.add(race1)

    race2_dt = (now - timedelta(days=10)).replace(hour=10, minute=0, second=0, microsecond=0)
    race2 = Event(
        name="District Fun Run",
        slug=event_slug("District Fun Run", race2_dt),
        start_datetime=race2_dt,
        end_datetime=race2_dt.replace(hour=12, minute=0),
        type=EventType.race,
        status=EventStatus.completed,
        results_expected=True,
        distance=2.0,
        distance_unit=DistanceUnit.kilometers,
        location_name="Seneca Park",
        street_address="3151 Pee Wee Reese Rd, Louisville, KY 40207",
        arrival_datetime=race2_dt - timedelta(minutes=45),
        description="District-wide fun run at Seneca Park. Wear your team shirt!",
    )
    session.add(race2)

    # Future event (upcoming race)
    future_dt = (now + timedelta(days=10)).replace(hour=9, minute=30, second=0, microsecond=0)
    future_race = Event(
        name="Fall Classic",
        slug=event_slug("Fall Classic", future_dt),
        start_datetime=future_dt,
        end_datetime=future_dt.replace(hour=11, minute=30),
        type=EventType.race,
        status=EventStatus.scheduled,
        results_expected=True,
        distance=1.0,
        distance_unit=DistanceUnit.miles,
        location_name="Cherokee Park",
        street_address="745 Cochran Hill Rd, Louisville, KY 40206",
        arrival_datetime=future_dt - timedelta(hours=1),
        description="Seasonal classic race. Pack water and snacks.",
    )
    session.add(future_race)

    # Cancelled event
    cancelled_dt = (now + timedelta(days=3)).replace(hour=15, minute=30, second=0, microsecond=0)
    cancelled = Event(
        name="Thursday Practice",
        slug=event_slug("Thursday Practice", cancelled_dt),
        start_datetime=cancelled_dt,
        type=EventType.practice,
        status=EventStatus.cancelled,
        results_expected=False,
        distance=1.0,
        distance_unit=DistanceUnit.miles,
        location_name="Hite Elementary Field",
        description="Cancelled due to weather.",
    )
    session.add(cancelled)

    # Postponed event
    postponed_dt = (now + timedelta(days=5)).replace(hour=16, minute=0, second=0, microsecond=0)
    postponed = Event(
        name="Team Meeting",
        slug=event_slug("Team Meeting", postponed_dt),
        start_datetime=postponed_dt,
        type=EventType.team_meeting,
        status=EventStatus.postponed,
        results_expected=False,
        location_name="Hite Elementary Gym",
        description="Postponed from the original date. New date TBD.",
    )
    session.add(postponed)

    # Future practice
    future_practice_dt = (now + timedelta(days=2)).replace(hour=15, minute=30, second=0, microsecond=0)
    future_practice = Event(
        name="Timed Mile #5",
        slug=event_slug("Timed Mile 5", future_practice_dt),
        start_datetime=future_practice_dt,
        end_datetime=future_practice_dt.replace(hour=16, minute=30),
        type=EventType.practice,
        status=EventStatus.scheduled,
        results_expected=True,
        distance=1.0,
        distance_unit=DistanceUnit.miles,
        location_name="Hite Elementary Field",
        description="Weekly timed mile practice.",
    )
    session.add(future_practice)

    session.flush()

    # ── Results ──────────────────────────────────────────────────────
    # Different students have different numbers of results.
    # Times in seconds; a 1-mile time for an elementary student ~6:00–12:00.

    # Base times (seconds) per student — these represent ~ability level
    base_times = {
        "Robert": 540,   # 9:00
        "Jane": 510,     # 8:30
        "Alex": 600,     # 10:00
        "Maria": 525,    # 8:45
        "Ethan": 480,    # 8:00 (fastest)
        "Lily": 570,     # 9:30
        "Sam": 555,      # 9:15
        "Olivia": 495,   # 8:15
    }

    import random
    random.seed(42)  # reproducible

    all_timed_events = practices + [race1, race2]

    for student in students:
        base = base_times[student.first_name]

        # Not all students have results for every event
        # Robert, Jane, Ethan: all events; others: subset
        if student.first_name in ("Robert", "Jane", "Ethan"):
            events_for_student = all_timed_events
        elif student.first_name in ("Alex", "Maria"):
            events_for_student = all_timed_events[:4]  # practices only
        elif student.first_name == "Lily":
            events_for_student = all_timed_events[:2]  # just 2 events
        elif student.first_name == "Sam":
            events_for_student = all_timed_events[1:5]  # skip first, include race1
        else:  # Olivia
            events_for_student = all_timed_events[2:]   # last 2 practices + both races

        for j, evt in enumerate(events_for_student):
            # Slight improvement over time + random variation
            improvement = j * 3  # 3 seconds faster each event
            variation = random.randint(-8, 8)
            time_secs = max(base - improvement + variation, 240)  # floor at 4:00

            # Scale for 2km race
            if evt == race2:
                time_secs = int(time_secs * 1.25)  # 2km takes ~25% longer than 1 mile for kids

            r = Result(
                student_id=student.id,
                event_id=evt.id,
                time_seconds=time_secs,
                status=ResultStatus.completed,
                placement=None,  # Phase 2 can add placements
            )
            session.add(r)

    # Add a DNF result for Alex on race1 (to show varied statuses)
    dnf = Result(
        student_id=students[2].id,  # Alex
        event_id=race1.id,
        time_seconds=None,
        status=ResultStatus.did_not_finish,
        notes="Stopped at halfway due to side stitch.",
    )
    session.add(dnf)

    # Add DNP result for Lily on race2
    dnp = Result(
        student_id=students[5].id,  # Lily
        event_id=race2.id,
        time_seconds=None,
        status=ResultStatus.did_not_participate,
        notes="Absent.",
    )
    session.add(dnp)

    session.commit()
    print(f"✅ Seeded {len(students)} students, {len(all_timed_events) + 4} events, and results.")


def main():
    parser = argparse.ArgumentParser(description="Seed the Hite XC database")
    parser.add_argument("--force", action="store_true", help="Drop and recreate all data")
    args = parser.parse_args()

    init_db()
    session = SessionLocal()

    if db_has_data(session):
        if not args.force:
            print("❌ Database already contains data. Use --force to wipe and re-seed.")
            sys.exit(1)
        print("⚠️  --force: dropping all data …")
        Base.metadata.drop_all(bind=engine())
        Base.metadata.create_all(bind=engine())
        session = SessionLocal()  # new session after drop

    seed(session)
    session.close()


if __name__ == "__main__":
    main()
