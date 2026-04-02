"""
Celery worker — task definition and application factory.

Each task message must contain:
    {"hashtag": "<string>"}

Startup
-------
    celery -A worker worker --loglevel=info --concurrency=<N>

where N = number of connected Android devices.

The worker uses a *prefork* pool (default).  Each child process handles
one task at a time, so set --concurrency equal to the number of devices
you want to run in parallel.

Device allocation
-----------------
On task start the worker iterates connected ADB devices and acquires the
first one that is not already locked by another worker process.  If all
devices are busy the task raises `Retry` so Celery re-queues it after a
short delay (without counting against the retry limit).
"""

import logging
import sys

from celery import Celery
from celery.exceptions import Ignore
from celery.utils.log import get_task_logger

import config
import models
from device_manager import (
    DeviceDisconnectedError,
    acquire_device,
    list_connected_devices,
    pick_available_device,
)
from scraper_core import run_scrape

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = get_task_logger(__name__)

# ── Celery application ────────────────────────────────────────────────────────

app = Celery(
    "mobilescraper",
    broker=config.CLOUDAMQP_URL,
    # No result backend — we persist directly to PostgreSQL
    backend=None,
)

app.conf.update(
    # Use the queue name from config
    task_default_queue=config.CELERY_QUEUE_NAME,
    # Acknowledge the message only after the task finishes (safer)
    task_acks_late=True,
    # Do NOT prefetch more than one task per worker child
    worker_prefetch_multiplier=1,
    # Serialisation
    task_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # No automatic retries — failures are terminal
    task_max_retries=0,
)


# ── Initialise DB on worker startup ──────────────────────────────────────────

@app.on_after_configure.connect
def setup_db(sender, **kwargs):
    models.init_db()


# ── Task ──────────────────────────────────────────────────────────────────────

@app.task(
    name="scrape_hashtag",
    bind=True,
    max_retries=None,       # unlimited retries for "device busy" back-off only
    default_retry_delay=10, # seconds to wait before re-queuing when all devices busy
)
def scrape_hashtag(self, hashtag: str) -> None:
    """
    Celery task: scrape TikTok for *hashtag* and persist results.

    Message payload::

        {"hashtag": "#wardah"}

    Failure policy
    --------------
    - Device busy   → re-queue after 10 s (transparent to the user)
    - Device disconnected / scrape error → log + stop (no retry)
    """
    logger.info("Task received — hashtag=%r", hashtag)

    # ── 1. Pick an available device ───────────────────────────────────────────
    serial = pick_available_device()
    if serial is None:
        logger.warning("All devices busy — re-queuing task for hashtag=%r", hashtag)
        # Retry without counting against max_retries (device-busy is transient)
        raise self.retry(countdown=10, max_retries=None)

    # ── 2. Lock the device and run the scrape ─────────────────────────────────
    try:
        with acquire_device(serial):
            video_ids = run_scrape(serial, hashtag)

    except DeviceDisconnectedError as exc:
        # Device vanished mid-task — log and stop permanently
        logger.error(
            "Device %s disconnected during scrape for hashtag=%r: %s",
            serial, hashtag, exc,
        )
        # Raise Ignore so Celery marks the task as failed without retrying
        raise Ignore() from exc

    except Exception as exc:
        logger.error(
            "Scrape failed for hashtag=%r on device %s: %s",
            hashtag, serial, exc,
            exc_info=True,
        )
        raise Ignore() from exc

    # ── 3. Persist results ────────────────────────────────────────────────────
    if video_ids:
        inserted = models.save_video_ids(hashtag, video_ids)
        logger.info(
            "Persisted %d new video IDs for hashtag=%r",
            inserted, hashtag,
        )
    else:
        logger.warning("No video IDs collected for hashtag=%r", hashtag)

    logger.info("Task complete — hashtag=%r", hashtag)


# ── CLI helper: enqueue tasks from a list ─────────────────────────────────────

def enqueue_hashtags(hashtags: list[str]) -> None:
    """
    Convenience function to push a batch of hashtag tasks onto the queue.

    Usage (from a Python shell or script)::

        from worker import enqueue_hashtags
        enqueue_hashtags(["#wardah", "#skincare", "#beauty"])
    """
    for tag in hashtags:
        scrape_hashtag.apply_async(kwargs={"hashtag": tag})
        logger.info("Enqueued hashtag=%r", tag)


if __name__ == "__main__":
    # Quick smoke-test: print connected devices
    devices = list_connected_devices()
    print(f"Connected devices: {devices}")
    print("Start the worker with:")
    print(f"  celery -A worker worker --loglevel=info --concurrency={max(len(devices), 1)}")
