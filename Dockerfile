FROM python:3.12-slim

# Non-root user
RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid app --shell /bin/bash --create-home app

WORKDIR /app

# Install dependencies first (layer caching); no cache keeps the image small
COPY pyproject.toml ./
RUN pip install --no-cache-dir . && pip cache purge

# Copy application code (templates, static, scripts — no dev/test files)
COPY app/ app/
COPY templates/ templates/
COPY static/ static/
COPY scripts/ scripts/

# /data is the PVC mount point in prod. Create it here so the app can also
# run locally without the mount. fsGroup in the k8s PodSpec grants the app
# user write access in the cluster; chown ensures it also works locally.
RUN mkdir -p /data && chown app:app /data

# Switch to non-root before declaring the volume
USER app

ENV HITE_DB_PATH=/data/hite.db
ENV HITE_SNAPSHOT_PATH=/data/snapshots/hite.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

# Single worker — SQLite is a single-writer database
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1"]
