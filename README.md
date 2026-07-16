# Hite Elementary Cross Country

Mobile-friendly website for the Hite Elementary cross country team:
public student results, progress graphs, event calendar, and a
password-protected coach admin area.

- Requirements: `docs/PRD.txt`
- Stack: Python / FastAPI / SQLAlchemy / Jinja2 / SQLite / Chart.js
- Deploy: any single-pod container runtime; see `docs/DEPLOYMENT.md` for
  the runtime contract (env vars, volumes, health checks, backup snapshots).

Public site is noindex'd (robots meta + X-Robots-Tag); students shown as
first name + last initial.
