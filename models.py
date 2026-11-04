from datetime import datetime, timezone
from enum import Enum
from sqlalchemy import DateTime, Enum as SAEnum, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ContentFormat(str, Enum):
    POST = "POST"
    CAROUSEL = "CAROUSEL"
    REEL = "REEL"
    STORY = "STORY"


class ContentStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    format: Mapped[ContentFormat] = mapped_column(SAEnum(ContentFormat), nullable=False)
    status: Mapped[ContentStatus] = mapped_column(SAEnum(ContentStatus), default=ContentStatus.DRAFT, index=True)
    caption: Mapped[str] = mapped_column(Text, default="")
    ai_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    media_urls: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    insights_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    instagram_media_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
