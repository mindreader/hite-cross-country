FROM python:3.12-slim AS base

# Non-root user
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid app --shell /bin/bash --create-home app

WORKDIR /app

# Install dependencies first (layer caching)
COPY pyproject.toml ./
RUN pip install --no-cache-dir . && pip cache purge

# Copy application code
COPY app/ app/
COPY templates/ templates/
COPY static/ static/
COPY scripts/ scripts/

# Data volume
RUN mkdir -p /app/data && chown app:app /app/data
VOLUME /app/data

# Switch to non-root
USER app

ENV HITE_DB_PATH=/app/data/hite.db
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
