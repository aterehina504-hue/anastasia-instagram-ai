import logging
from datetime import datetime, timezone
from sqlalchemy import select
from app.db import SessionLocal
from app.models import ContentItem, ContentStatus
from app.services.instagram import InstagramPublisher

logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def publish_due_items() -> None:
    """Publish approved items whose scheduled time has arrived.

    Run exactly one app worker/scheduler instance for this starter project.
    The DB status transition is committed before calling Meta to reduce duplicates.
    """
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        candidates = db.scalars(
            select(ContentItem)
            .where(ContentItem.status == ContentStatus.APPROVED)
            .order_by(ContentItem.scheduled_at.asc())
            .limit(5)
        ).all()
        item_ids = [item.id for item in candidates if item.scheduled_at and _as_utc(item.scheduled_at) <= now]

    for item_id in item_ids:
        with SessionLocal() as db:
            item = db.get(ContentItem, item_id)
            if not item or item.status != ContentStatus.APPROVED:
                continue
            item.status = ContentStatus.PUBLISHING
            item.error_message = None
            db.commit()
            fmt, media_urls, caption = item.format, list(item.media_urls or []), item.caption

        try:
            publisher = InstagramPublisher()
            media_id = publisher.publish(fmt, media_urls, caption)
            with SessionLocal() as db:
                item = db.get(ContentItem, item_id)
                if item:
                    item.status = ContentStatus.PUBLISHED
                    item.instagram_media_id = media_id
                    item.published_at = datetime.now(timezone.utc)
                    item.error_message = None
                    db.commit()
            logger.info("Published content item %s as Instagram media %s", item_id, media_id)
        except Exception as exc:  # keep the scheduler alive; expose error in the review panel
            logger.exception("Failed to publish content item %s", item_id)
            with SessionLocal() as db:
                item = db.get(ContentItem, item_id)
                if item:
                    item.status = ContentStatus.FAILED
                    item.error_message = str(exc)[:4000]
                    db.commit()


def collect_due_insights() -> None:
    """Refresh media insights after an initial 48-hour delay to allow Meta metrics to settle."""
    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - 48 * 60 * 60
    with SessionLocal() as db:
        published = db.scalars(
            select(ContentItem).where(
                ContentItem.status == ContentStatus.PUBLISHED,
                ContentItem.instagram_media_id.is_not(None),
            )
        ).all()
        due_ids = []
        for item in published:
            if not item.published_at:
                continue
            published_at = _as_utc(item.published_at)
            updated_at = _as_utc(item.insights_updated_at) if item.insights_updated_at else None
            if published_at.timestamp() <= cutoff and (updated_at is None or (now - updated_at).total_seconds() >= 24 * 3600):
                due_ids.append(item.id)

    if not due_ids:
        return

    try:
        publisher = InstagramPublisher()
    except Exception:
        logger.exception("Cannot initialise Instagram API for insights collection")
        return

    for item_id in due_ids:
        with SessionLocal() as db:
            item = db.get(ContentItem, item_id)
            if not item or not item.instagram_media_id:
                continue
            media_id = item.instagram_media_id
        try:
            metrics = publisher.get_media_insights(media_id)
            with SessionLocal() as db:
                item = db.get(ContentItem, item_id)
                if item:
                    item.metrics = metrics
                    item.insights_updated_at = datetime.now(timezone.utc)
                    db.commit()
        except Exception:
            logger.exception("Could not refresh insights for content item %s", item_id)
