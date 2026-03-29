"""
Central configuration — reads from environment variables with sensible defaults.
Copy .env.example to .env and fill in your values.
"""

import os

# ── Broker ────────────────────────────────────────────────────────────────────
CLOUDAMQP_URL: str = os.environ["CLOUDAMQP_URL"]  # required — no default

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.environ["DATABASE_URL"]  # required — e.g. postgresql+psycopg2://user:pass@host/db

# ── TikTok / ADB ─────────────────────────────────────────────────────────────
TIKTOK_PKG: str = os.getenv("TIKTOK_PKG", "com.zhiliaoapp.musically")
SCROLL_DELAY: float = float(os.getenv("SCROLL_DELAY", "5"))

# ── Celery ────────────────────────────────────────────────────────────────────
CELERY_QUEUE_NAME: str = os.getenv("CELERY_QUEUE_NAME", "scrape_tasks")
