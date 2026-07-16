"""
Public-facing routes: home, students, student detail.

URL ownership:
  /              – Home page
  /students      – Student directory
  /students/{slug} – Individual student results page
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import templates

router = APIRouter(tags=["public"])


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Session = Depends(get_db)):
    """Home page: student search, directory preview, upcoming events."""
    return templates.TemplateResponse(request, "public/home.html")


@router.get("/students", response_class=HTMLResponse)
async def student_directory(request: Request, db: Session = Depends(get_db)):
    """Alphabetical student directory with optional search."""
    return templates.TemplateResponse(request, "public/students.html")


@router.get("/students/{slug}", response_class=HTMLResponse)
async def student_detail(slug: str, request: Request, db: Session = Depends(get_db)):
    """Individual student results page with progress graph."""
    return templates.TemplateResponse(request, "public/student_detail.html", {"slug": slug})
