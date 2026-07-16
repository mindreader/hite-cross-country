# Hite Elementary Cross Country — Architecture

> **Phase 1 scaffold** — the shared contract for Phase 2 parallel agents.

## Stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.12 |
| Framework | FastAPI |
| ORM | SQLAlchemy 2.x (sync) |
| Templates | Jinja2 (server-rendered) |
| Database | SQLite (WAL mode) |
| Auth | Signed cookie sessions (itsdangerous + bcrypt) |
| CSS | Hand-rolled, no framework |
| Charts | Chart.js (added by Phase 2; scaffold doesn't include it) |

## Project layout

```
.
├── app/
│   ├── __init__.py
│   ├── main.py            # App factory, middleware, Jinja globals
│   ├── db.py              # Engine, SessionLocal, get_db dependency, init_db
│   ├── models.py          # SQLAlchemy ORM: Student, Event, Result + enums
│   ├── auth.py            # Coach auth: password check, session cookies, require_coach
│   ├── util.py            # Shared helpers: time fmt, slugs, display names, TZ
│   └── routers/
│       ├── __init__.py
│       ├── public.py      # /  /students  /students/{slug}
│       ├── events.py      # /events  /events/{slug}  /upcoming  /calendar
│       └── admin.py       # /coach/*
├── templates/
│   ├── base.html          # Master layout — extend this
│   ├── public/            # Templates owned by public router
│   ├── events/            # Templates owned by events router
│   └── admin/             # Templates owned by admin router
├── static/
│   └── css/style.css      # Design tokens + base styles
├── scripts/
│   └── seed.py            # Sample data seeder
├── tests/                 # Pytest smoke tests
├── data/                  # SQLite DB lives here (gitignored)
├── Dockerfile
├── pyproject.toml
└── docs/
    ├── PRD.txt
    └── ARCHITECTURE.md    # ← you are here
```

## URL scheme & router ownership

Each router owns a non-overlapping URL prefix. Phase 2 agents add page
logic inside the appropriate router file and its template directory.

| Router | File | URLs | Template dir |
|--------|------|------|-------------|
| **public** | `app/routers/public.py` | `/`, `/students`, `/students/{slug}` | `templates/public/` |
| **events** | `app/routers/events.py` | `/events`, `/events/{slug}`, `/upcoming`, `/calendar` | `templates/events/` |
| **admin** | `app/routers/admin.py` | `/coach`, `/coach/login`, `/coach/logout`, `/coach/students*`, `/coach/events*` | `templates/admin/` |
| **healthz** | `app/main.py` (inline) | `/healthz` | — |

## Timezone convention

**All datetimes in the database are stored as naive local time in
`America/Kentucky/Louisville`** (US Eastern with DST).

- `app/util.now_local()` is the single source of "current time."
- Comparisons (upcoming vs past) use `now_local()`.
- No `datetime.utcnow()` anywhere — all naive datetimes mean Louisville local.
- If you need aware datetimes for ical export, attach `app/util.TZ`.

**Why naive-local?** The audience is a single school in Louisville. Storing
UTC and converting would add complexity with zero benefit. Naive-local
avoids confusion in templates and seed data.

## Data model

Three tables: `students`, `events`, `results`.

### Enums

```python
EventType:   practice | race | team_meeting | other
EventStatus: scheduled | postponed | cancelled | completed
DistanceUnit: miles | kilometers | meters
ResultStatus: completed | did_not_participate | did_not_finish | excused | disqualified
```

### Key constraints

- `results.student_id + event_id` has a **unique constraint** (no duplicate results).
- Cascade deletes: deleting a student or event removes related results.
- `students.slug` and `events.slug` are **unique indexed** for fast URL lookups.

### Indexes

- `students`: slug (unique), last_name+first_name, active
- `events`: slug (unique), start_datetime, type, status
- `results`: student_id, event_id

### Slug format

- **Student**: `{first}-{last}` → `robert-watson`
- **Event**: `{name}-{YYYY-MM-DD}` → `hite-invitational-2026-08-30`

Use `app.util.student_slug()` and `app.util.event_slug()` to generate.

## Template block structure

`base.html` defines these blocks:

| Block | Purpose |
|-------|---------|
| `title` | `<title>` content |
| `head_extra` | Extra `<head>` tags (CSS, meta) |
| `content` | Main page content |
| `scripts` | Bottom-of-body `<script>` tags |

Every page template should `{% extends "base.html" %}` and fill `content`
at minimum.

## CSS conventions

All design tokens are CSS custom properties on `:root` in `static/css/style.css`.

### Result treatment classes

| Class | Appearance |
|-------|-----------|
| `.result-race` | Light red bg, darker red left border |
| `.result-practice` | Light yellow bg, darker yellow left border |
| `.result-other` | Neutral grey bg, grey left border |
| `.badge-race` | Small race pill |
| `.badge-practice` | Small practice pill |
| `.badge-cancelled` | Cancelled status pill |
| `.badge-postponed` | Postponed status pill |

### Layout utilities

`.container`, `.card`, `.btn`, `.btn-primary`, `.btn-secondary`,
`.btn-danger`, `.form-group`, `.table-wrap`, `.table-stack`, `.empty-state`,
`.alert`, `.alert-error`, `.alert-success`, `.alert-warning`, `.time-display`

## Auth flow

1. Coach visits `/coach/login`, enters password.
2. `auth.verify_password()` checks against `HITE_COACH_PASSWORD_HASH` (bcrypt) or dev fallback.
3. On success, a signed cookie `hite_session` is set via `itsdangerous.URLSafeTimedSerializer`.
4. Protected routes use `Depends(require_coach)` — redirects to login if cookie absent/invalid.
5. Logout POSTs to `/coach/logout`, which clears the cookie.

### Environment variables

| Var | Required | Default |
|-----|----------|---------|
| `HITE_DB_PATH` | No | `./data/hite.db` |
| `HITE_COACH_PASSWORD_HASH` | Prod: yes | Dev: accepts `devcoach` |
| `HITE_SESSION_SECRET` | Prod: yes | Dev: random (sessions lost on restart) |

## Jinja2 globals & filters

Available in all templates (registered in `main.py`):

| Name | Type | Purpose |
|------|------|---------|
| `seconds_to_mmss(n)` | global/filter | `540` → `"9:00"` |
| `now_local()` | global | Current naive-local datetime |
| `is_upcoming(dt)` | global | Bool: datetime is in the future |
| `is_past(dt)` | global | Bool: datetime is in the past |
| `n|mmss` | filter | Same as `seconds_to_mmss` |

## How Phase 2 agents should add pages

### Rules to avoid collisions

1. **Stay in your router and template directory.** The public agent touches
   `app/routers/public.py` and `templates/public/`. The events agent
   touches `app/routers/events.py` and `templates/events/`. The admin
   agent touches `app/routers/admin.py` and `templates/admin/`.

2. **Don't modify `app/main.py`, `app/db.py`, `app/models.py`, or
   `app/auth.py`** without coordinating with the scaffold owner. If you
   need a new model field, a new Jinja global, or a new dependency,
   propose it.

3. **Use `app.util` helpers** — don't reinvent time formatting or slug
   generation.

4. **Use `app.db.get_db`** as the FastAPI `Depends` for database access.

5. **Use `app.auth.require_coach`** as the `Depends` for any coach-only route.

6. **Extend `base.html`** and fill `{% block content %}`. Add page-specific
   JS in `{% block scripts %}`.

7. **Add new CSS** by appending to `static/css/style.css` — or create a
   new file and include it via `{% block head_extra %}`. Reuse existing
   tokens and classes.

8. **Keep templates in the right sub-directory** matching your router.

### Adding a new page (example)

```python
# In app/routers/public.py — add a new route
@router.get("/students", response_class=HTMLResponse)
async def student_directory(request: Request, db: Session = Depends(get_db)):
    students = db.query(Student).filter(Student.active).order_by(Student.last_name).all()
    return templates.TemplateResponse(request, "public/students.html", {
        "students": students,
    })
```

**Important:** Use `templates.TemplateResponse(request, "name.html", context)`
(Starlette 1.3+ API). The `request` is the first argument, the template name
is second, and context is an optional third dict. Do NOT put `request` inside
the context dict.

```html
{# In templates/public/students.html #}
{% extends "base.html" %}
{% block title %}Students{% endblock %}
{% block content %}
<h1>Student Directory</h1>
{% for s in students %}
  <a href="/students/{{ s.slug }}">{{ s.public_display_name }}</a>
{% endfor %}
{% endblock %}
```

## Middleware

- **X-Robots-Tag: noindex, nofollow** — added to every response via middleware in `main.py`.
- `<meta name="robots" content="noindex, nofollow">` is also in `base.html`.

## Running locally

```bash
pip install -e ".[dev]"
python scripts/seed.py
uvicorn app.main:app --reload
# Visit http://localhost:8000
# Coach login: http://localhost:8000/coach/login  (password: devcoach)
```

## Running tests

```bash
pytest
```
