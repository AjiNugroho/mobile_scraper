# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build deps for psycopg2-binary (already bundled, but keeps layer clean)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# android-tools-adb provides the `adb` binary
RUN apt-get update && apt-get install -y --no-install-recommends \
        android-tools-adb \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY . .

# The worker process writes device lock files here; make sure the dir exists
RUN mkdir -p /tmp/mobilescraper_locks

# Default command — override concurrency via CELERY_CONCURRENCY env var
ENV CELERY_CONCURRENCY=1

CMD celery -A worker worker \
        --loglevel=info \
        --concurrency=${CELERY_CONCURRENCY} \
        --pool=prefork \
        --hostname=${CELERY_WORKER_NAME:-worker}@%h \
        --events
