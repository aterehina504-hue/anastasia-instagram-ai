import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.config import settings
from app.db import SessionLocal
from app.models import ContentFormat, ContentItem, ContentStatus
from app.services.ai import generate_content, generate_daily_topics
from app.services.media import create_ai_assets

logger = logging.getLogger(__name__)


def generate_daily_drafts() -> None:
    """Build today's drafts. These remain DRAFT until a human approves them."""
    count = max(1, min(settings.daily_draft_count, 3))
    allowed_formats = [x.strip().upper() for x in settings.daily_formats.split(",") if x.strip()]
    valid_formats = {fmt.value for fmt in ContentFormat}
    allowed_formats = [fmt for fmt in allowed_formats if fmt in valid_formats]
    if not allowed_formats:
        allowed_formats = ["POST", "CAROUSEL", "REEL", "STORY"]

    tz = ZoneInfo(settings.app_timezone)
    now_local = datetime.now(tz)
    with SessionLocal() as db:
        existing_items = db.scalars(
            select(ContentItem).where(ContentItem.source == "daily_ai")
        ).all()
        for existing_item in existing_items:
            created = existing_item.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created.astimezone(tz).date() == now_local.date():
                logger.info("Daily AI drafts already exist for %s; skipping", now_local.date())
                return

    topics = generate_daily_topics(
        count=count,
        brand_name=settings.brand_name,
        industry=settings.brand_industry,
        audience=settings.brand_audience,
        tone=settings.brand_tone,
        offer=settings.brand_offer,
        allowed_formats=allowed_formats,
    )
    for plan in topics:
        content_format = ContentFormat(plan["format"])
        try:
            payload = generate_content(
                topic=plan["topic"],
                content_format=content_format,
                brand_name=settings.brand_name,
                industry=settings.brand_industry,
                audience=settings.brand_audience,
                tone=settings.brand_tone,
                offer=settings.brand_offer,
            )
            assets = create_ai_assets(content_format, payload, settings.brand_name)
            with SessionLocal() as db:
                db.add(ContentItem(
                    topic=plan["topic"],
                    source="daily_ai",
                    format=content_format,
                    status=ContentStatus.DRAFT,
                    caption=payload.get("caption", ""),
                    ai_payload=payload,
                    media_urls=assets,
                ))
                db.commit()
        except Exception:
            logger.exception("Failed to create daily draft: %s", plan.get("topic"))

