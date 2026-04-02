# MobileScraper — Distributed TikTok Scraper

A production-ready distributed scraping system that runs TikTok UI automation
on real Android devices via ADB, coordinated by Celery + RabbitMQ (CloudAMQP),
with results stored in PostgreSQL.

---

## Architecture

```
CloudAMQP (RabbitMQ)
        │
        │  {"hashtag": "#wardah"}
        ▼
  Celery Worker(s)
        │
        ├── device_manager.py  ← picks & locks an ADB device
        ├── scraper_core.py    ← runs TikTok UI automation
        └── models.py          ← persists video IDs to PostgreSQL
```

### File map

| File | Responsibility |
|---|---|
| `config.py` | Reads all config from environment variables |
| `models.py` | SQLAlchemy ORM model + `save_video_ids()` helper |
| `device_manager.py` | ADB device discovery, file-lock-based exclusive allocation |
| `scraper_core.py` | All TikTok UI automation (extracted from legacy script) |
| `worker.py` | Celery app + `scrape_hashtag` task |
| `automator_mobile.py` | Legacy standalone script (kept for reference) |

---

## Prerequisites

- Python 3.11+
- Android SDK platform-tools (`adb` in PATH)
- At least one Android device connected via USB with USB debugging enabled
- PostgreSQL database
- CloudAMQP account (free tier works)

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Initialise uiautomator2 on each device

Run once per device (with the device connected):

```bash
python -m uiautomator2 init
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in CLOUDAMQP_URL and DATABASE_URL
export $(cat .env | xargs)
```

### 4. Create the database table

```bash
python - <<'EOF'
from models import init_db
init_db()
print("Done.")
EOF
```

---

## Running the worker

### Option A — Docker Compose (recommended)

```bash
# 1. Fill in your credentials
cp .env.example .env
# edit .env: set CLOUDAMQP_URL, DATABASE_URL, CELERY_CONCURRENCY

# 2. Make sure your Android device(s) are connected and authorised on the HOST
adb devices

# 3. Build and start
docker compose up --build

# Scale to N devices (each container = one worker process)
docker compose up --build --scale worker=3

# View logs
docker compose logs -f worker

# Stop
docker compose down
```

> **ADB note:** The compose file mounts the host ADB socket so the container
> reuses the already-authorised host ADB server.  Run `adb start-server` on
> the host before starting the container.

### Option B — Local (no Docker)

```bash
export $(cat .env | xargs)

# Detect connected devices
python worker.py
# Prints: Connected devices: ['emulator-5554', 'R3CN90XXXXX']

# Start the worker — set --concurrency to number of devices
celery -A worker worker --loglevel=info --concurrency=2
```

Each worker child process handles exactly one task at a time.  With 2 devices
and 5 queued tasks, 2 tasks run in parallel and 3 wait in the queue.

---

## Enqueuing tasks

### From a Python script

```python
from worker import enqueue_hashtags

enqueue_hashtags(["#wardah", "#skincare", "#beauty"])
```

### From the Celery API directly

```python
from worker import scrape_hashtag

scrape_hashtag.apply_async(kwargs={"hashtag": "#wardah"})
```

### From the command line (single task)

```bash
celery -A worker call scrape_hashtag --kwargs='{"hashtag": "#wardah"}'
```

---

## Database schema

```sql
CREATE TABLE scraped_videos (
    hashtag  TEXT NOT NULL,
    video_id TEXT NOT NULL,
    PRIMARY KEY (hashtag, video_id)
);
```

`models.init_db()` creates this table automatically via SQLAlchemy.

### Neon DB setup

1. Create a free project at [neon.tech](https://neon.tech).
2. Go to **Connection Details** and copy the **Connection string**.
3. Append `?sslmode=require` if not already present.
4. Paste it as `DATABASE_URL` in your `.env`:

```
DATABASE_URL=postgresql+psycopg2://user:password@ep-xxx-yyy.us-east-2.aws.neon.tech/neondb?sslmode=require
```

---

## Failure handling

| Scenario | Behaviour |
|---|---|
| All devices busy | Task re-queued after 10 s (transparent) |
| Device disconnects mid-task | Task logged as failed, **not** retried |
| Scrape raises an exception | Task logged as failed, **not** retried |
| Duplicate video ID | Silently ignored (`ON CONFLICT DO NOTHING`) |

---

## Multi-machine scaling

Run the same worker command on multiple machines that share the same
CloudAMQP broker and PostgreSQL database.  Each machine manages its own
locally connected ADB devices.  The file locks in `/tmp/mobilescraper_locks/`
are local to each machine, which is correct — two machines cannot share a
physical USB device.
