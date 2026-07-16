"""
SQLAlchemy ORM models for Hite XC.

All datetime columns store naive local time in America/Kentucky/Louisville.
See docs/ARCHITECTURE.md for the rationale.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ── Enums ──────────────────────────────────────────────────────────────


class EventType(str, enum.Enum):
    practice = "practice"
    race = "race"
    team_meeting = "team_meeting"
    other = "other"


class EventStatus(str, enum.Enum):
    scheduled = "scheduled"
    postponed = "postponed"
    cancelled = "cancelled"
    completed = "completed"


class DistanceUnit(str, enum.Enum):
    miles = "miles"
    kilometers = "kilometers"
    meters = "meters"


class ResultStatus(str, enum.Enum):
    completed = "completed"
    did_not_participate = "did_not_participate"
    did_not_finish = "did_not_finish"
    excused = "excused"
    disqualified = "disqualified"


# ── Models ─────────────────────────────────────────────────────────────


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, autoincrement=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    display_name = Column(String(200), nullable=True, doc="Override display name; auto-generated if NULL")
    slug = Column(String(200), nullable=False, unique=True, index=True)
    grade = Column(Integer, nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    results = relationship("Result", back_populates="student", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("ix_students_last_first", "last_name", "first_name"),
        Index("ix_students_active", "active"),
    )

    @property
    def public_display_name(self) -> str:
        """First name + last initial, e.g. 'Robert W.'"""
        if self.display_name:
            return self.display_name
        initial = self.last_name[0].upper() if self.last_name else ""
        return f"{self.first_name} {initial}."

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    slug = Column(String(250), nullable=False, unique=True, index=True)
    start_datetime = Column(DateTime, nullable=False, doc="Naive local time (America/Kentucky/Louisville)")
    end_datetime = Column(DateTime, nullable=True)
    type = Column(Enum(EventType), nullable=False)
    status = Column(Enum(EventStatus), nullable=False, default=EventStatus.scheduled)
    results_expected = Column(Boolean, nullable=False, default=True)
    distance = Column(Float, nullable=True, doc="Numeric distance value")
    distance_unit = Column(Enum(DistanceUnit), nullable=True)
    location_name = Column(String(200), nullable=True)
    street_address = Column(String(300), nullable=True)
    arrival_datetime = Column(DateTime, nullable=True)
    description = Column(Text, nullable=True, doc="Public coach instructions / description")
    internal_notes = Column(Text, nullable=True, doc="Coach-only notes, never shown publicly")
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    results = relationship("Result", back_populates="event", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("ix_events_start", "start_datetime"),
        Index("ix_events_type", "type"),
        Index("ix_events_status", "status"),
    )

    @property
    def distance_label(self) -> str | None:
        if self.distance is None:
            return None
        unit = self.distance_unit.value if self.distance_unit else ""
        # Clean display: "1.0 miles" → "1 mile", "0.5 miles"
        dist = int(self.distance) if self.distance == int(self.distance) else self.distance
        return f"{dist} {unit}"


class Result(Base):
    __tablename__ = "results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    time_seconds = Column(Integer, nullable=True, doc="NULL when status != completed")
    status = Column(Enum(ResultStatus), nullable=False, default=ResultStatus.completed)
    placement = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    student = relationship("Student", back_populates="results")
    event = relationship("Event", back_populates="results")

    __table_args__ = (
        UniqueConstraint("student_id", "event_id", name="uq_student_event"),
        Index("ix_results_student", "student_id"),
        Index("ix_results_event", "event_id"),
    )
