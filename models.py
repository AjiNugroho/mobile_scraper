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
from sqlalchemy.orm import declarative_base
from sqlalchemy.dialects.postgresql import UUID
import uuid
from sqlalchemy import Column, String, create_engine,Text, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

import config

logger = logging.getLogger(__name__)


# ── ORM base ──────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class TiktokHashTagListingVideo(Base):
    __tablename__ = "tiktok_hashtag_listing_videos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(Text, nullable=False)
    hashtag = Column(Text, nullable=False)
    video_url = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<TiktokHashTagListingVideo(id={self.id}, hashtag={self.hashtag}, video_url={self.video_url})>"

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

def save_video_ids(hashtag: str, url_strings: list[str], request_id: str) -> int:
    """
    Persist a batch of video IDs for a given hashtag.

    Duplicate rows (same composite PK) are silently skipped via
    INSERT … ON CONFLICT DO NOTHING so the function is idempotent.

    Returns the number of newly inserted rows.
    """
    if not url_strings:
        return 0

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    rows = [
        {"hashtag": hashtag, 
         "video_url": url,
         "request_id": request_id
         }for url in url_strings
    ]

    with SessionLocal() as session:
        stmt = pg_insert(TiktokHashTagListingVideo).values(rows).on_conflict_do_nothing()
        result = session.execute(stmt)
        session.commit()
        inserted = result.rowcount
        logger.info(
            "Saved %d new video IDs for hashtag=%r",
            inserted, hashtag,
        )
        return inserted
