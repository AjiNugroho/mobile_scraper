"""
Database models and session factory.

Schema
------
scraped_videos
  hashtag   TEXT        — the searched hashtag (e.g. "#wardah")
  video_id  TEXT        — TikTok video ID extracted from the share URL
  PRIMARY KEY (hashtag, video_id)

Database: Neon (serverless PostgreSQL)
"""

import logging

from sqlalchemy import Column, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

import config

logger = logging.getLogger(__name__)


# ── ORM base ──────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class ScrapedVideo(Base):
    __tablename__ = "scraped_videos"

    hashtag  = Column(String, primary_key=True, nullable=False)
    video_id = Column(String, primary_key=True, nullable=False)

    def __repr__(self) -> str:
        return f"<ScrapedVideo hashtag={self.hashtag!r} video_id={self.video_id!r}>"


# ── Engine / session factory ──────────────────────────────────────────────────

_engine = create_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,   # detect stale connections
    # Neon requires SSL; the connection string already carries ?sslmode=require
    echo=False,
)

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=_engine,
    autocommit=False,
    autoflush=False,
)


def init_db() -> None:
    """Create all tables if they don't exist yet (idempotent)."""
    Base.metadata.create_all(_engine)
    logger.info("Database tables ensured.")


# ── Repository helper ─────────────────────────────────────────────────────────

def save_video_ids(hashtag: str, video_ids: list[str]) -> int:
    """
    Persist a batch of video IDs for a given hashtag.

    Duplicate rows (same composite PK) are silently skipped via
    INSERT … ON CONFLICT DO NOTHING so the function is idempotent.

    Returns the number of newly inserted rows.
    """
    if not video_ids:
        return 0

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    rows = [
        {"hashtag": hashtag, "video_id": vid}
        for vid in video_ids
    ]

    with SessionLocal() as session:
        stmt = pg_insert(ScrapedVideo).values(rows).on_conflict_do_nothing()
        result = session.execute(stmt)
        session.commit()
        inserted = result.rowcount
        logger.info(
            "Saved %d new video IDs for hashtag=%r",
            inserted, hashtag,
        )
        return inserted
