import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import settings
from app.db import Base, engine, get_db
from app.models import ContentFormat, ContentItem, ContentStatus
from app.security import require_admin
from app.services.ai import generate_content
from app.services.planner import generate_daily_drafts
from app.services.media import MEDIA_PATH, create_ai_assets, save_uploaded_file
from app.services.publisher import collect_due_insights, publish_due_items

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Instagram AI Content Factory", version="1.0.0")


@app.middleware("http")
async def same_origin_write_guard(request: Request, call_next):
    """Reject browser form submissions originating from a different site."""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site", "")
        if origin:
            parsed_origin = urlsplit(origin)
            request_host = request.headers.get("host", "")
            expected_scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
            if parsed_origin.netloc.lower() != request_host.lower() or parsed_origin.scheme != expected_scheme:
                return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
        elif fetch_site == "cross-site":
            return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
    return await call_next(request)


Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
scheduler = BackgroundScheduler(timezone="UTC")


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)
    if not scheduler.running:
        scheduler.add_job(
            publish_due_items,
            "interval",
            seconds=settings.scheduler_interval_seconds,
            id="publish_due_items",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        scheduler.add_job(
            collect_due_insights,
            "interval",
            hours=6,
            id="collect_due_insights",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        if settings.daily_drafts_enabled:
            scheduler.add_job(
                generate_daily_drafts,
                CronTrigger(
                    hour=settings.daily_generation_hour,
                    minute=settings.daily_generation_minute,
                    timezone=ZoneInfo(settings.app_timezone),
                ),
                id="generate_daily_drafts",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
            logger.info("Daily AI draft generation enabled")
        scheduler.start()
    logger.info("Instagram AI Content Factory started")


@app.on_event("shutdown")
def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "instagram-ai-content-factory"}


def _local_time(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(ZoneInfo(settings.app_timezone)).strftime("%d.%m.%Y %H:%M")


def _item_view(item: ContentItem) -> dict:
    return {
        "id": item.id,
        "topic": item.topic,
        "format": item.format.value,
        "status": item.status.value,
        "caption": item.caption,
        "ai_payload": item.ai_payload or {},
        "media_urls": item.media_urls or [],
        "scheduled_at": _local_time(item.scheduled_at),
        "published_at": _local_time(item.published_at),
        "instagram_media_id": item.instagram_media_id,
        "error_message": item.error_message,
        "created_at": _local_time(item.created_at),
        "source": item.source,
        "metrics": item.metrics or {},
    }


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    items = db.scalars(select(ContentItem).order_by(ContentItem.created_at.desc()).limit(100)).all()
    counts = {status.value: 0 for status in ContentStatus}
    for item in items:
        counts[item.status.value] += 1
    return templates.TemplateResponse(
        request,
        "index.html",
        context={
            "items": [_item_view(item) for item in items],
            "counts": counts,
            "timezone": settings.app_timezone,
            "generate_visuals": settings.generate_visuals,
        },
    )


@app.post("/generate")
def generate_draft(
    topic: str = Form(...),
    content_format: ContentFormat = Form(...),
    brand_name: str = Form("Компания"),
    industry: str = Form("Не указано"),
    audience: str = Form("Потенциальные клиенты компании"),
    tone: str = Form("Экспертный, дружелюбный, ясный"),
    offer: str = Form("Не указано"),
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    if not topic.strip():
        raise HTTPException(400, "Укажи тему публикации")
    try:
        payload = generate_content(topic, content_format, brand_name, industry, audience, tone, offer)
        caption = payload.get("caption", "")
        media_urls = create_ai_assets(content_format, payload, brand_name)
        item = ContentItem(
            topic=topic.strip(),
            format=content_format,
            status=ContentStatus.DRAFT,
            caption=caption,
            ai_payload=payload,
            media_urls=media_urls,
        )
        db.add(item)
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.exception("Could not generate a draft")
        raise HTTPException(502, f"Не удалось создать черновик: {exc}") from exc
    return RedirectResponse("/", status_code=303)


@app.post("/items/{item_id}/edit")
def edit_item(
    item_id: int,
    caption: str = Form(...),
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    item = db.get(ContentItem, item_id)
    if not item:
        raise HTTPException(404, "Публикация не найдена")
    if item.status not in {ContentStatus.DRAFT, ContentStatus.REJECTED, ContentStatus.FAILED}:
        raise HTTPException(409, "Нельзя редактировать материал после одобрения")
    if len(caption) > 2200:
        raise HTTPException(400, "Подпись Instagram не должна превышать 2200 символов")
    item.caption = caption
    item.status = ContentStatus.DRAFT
    item.error_message = None
    db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/items/{item_id}/upload")
def upload_media(
    item_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    item = db.get(ContentItem, item_id)
    if not item:
        raise HTTPException(404, "Публикация не найдена")
    if item.status not in {ContentStatus.DRAFT, ContentStatus.REJECTED, ContentStatus.FAILED}:
        raise HTTPException(409, "Медиа нельзя менять после одобрения")
    try:
        if item.format != ContentFormat.CAROUSEL and len(files) != 1:
            raise ValueError("Для этого формата загрузи ровно один файл за раз")
        new_urls = []
        for file in files:
            if file.size and file.size > settings.max_upload_mb * 1024 * 1024:
                raise ValueError(f"Файл больше лимита {settings.max_upload_mb} MB")
            if file.filename:
                url = save_uploaded_file(file.file, file.filename, item.format)
                new_urls.append(url)
        if item.format == ContentFormat.CAROUSEL:
            item.media_urls = list(item.media_urls or []) + new_urls
            if len(item.media_urls) > 10:
                raise ValueError("Карусель не может содержать более 10 изображений")
        else:
            if len(new_urls) != 1:
                raise ValueError("Для этого формата загрузите ровно один файл за раз")
            item.media_urls = new_urls
        item.status = ContentStatus.DRAFT
        item.error_message = None
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/", status_code=303)


@app.post("/items/{item_id}/approve")
def approve_item(
    item_id: int,
    scheduled_local: str = Form(""),
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    item = db.get(ContentItem, item_id)
    if not item:
        raise HTTPException(404, "Публикация не найдена")
    if item.status not in {ContentStatus.DRAFT, ContentStatus.REJECTED, ContentStatus.FAILED}:
        raise HTTPException(409, "Материал уже одобрен или опубликован")
    if not item.media_urls:
        raise HTTPException(400, "Сначала добавь медиафайл")
    if item.format == ContentFormat.CAROUSEL and not 2 <= len(item.media_urls) <= 10:
        raise HTTPException(400, "Для карусели нужно от 2 до 10 изображений")
    if item.format in {ContentFormat.POST, ContentFormat.STORY}:
        if len(item.media_urls) != 1:
            raise HTTPException(400, "Для поста или Stories нужен ровно один медиафайл")
    try:
        if scheduled_local.strip():
            local_dt = datetime.fromisoformat(scheduled_local)
            if local_dt.tzinfo is None:
                local_dt = local_dt.replace(tzinfo=ZoneInfo(settings.app_timezone))
            scheduled = local_dt.astimezone(timezone.utc)
        else:
            scheduled = datetime.now(timezone.utc)
    except ValueError as exc:
        raise HTTPException(400, "Неверная дата и время публикации") from exc
    if scheduled.timestamp() < datetime.now(timezone.utc).timestamp() - 60:
        raise HTTPException(400, "Дата публикации не должна быть в прошлом")
    item.status = ContentStatus.APPROVED
    item.scheduled_at = scheduled
    item.error_message = None
    db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/items/{item_id}/reject")
def reject_item(item_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    item = db.get(ContentItem, item_id)
    if not item:
        raise HTTPException(404, "Публикация не найдена")
    if item.status not in {ContentStatus.DRAFT, ContentStatus.FAILED}:
        raise HTTPException(409, "Нельзя отклонить этот материал в текущем статусе")
    item.status = ContentStatus.REJECTED
    item.error_message = None
    db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/items/{item_id}/retry")
def retry_item(item_id: int, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    item = db.get(ContentItem, item_id)
    if not item:
        raise HTTPException(404, "Публикация не найдена")
    if item.status != ContentStatus.FAILED:
        raise HTTPException(409, "Повторить можно только неудачную публикацию")
    item.status = ContentStatus.APPROVED
    item.scheduled_at = datetime.now(timezone.utc)
    item.error_message = None
    db.commit()
    return RedirectResponse("/", status_code=303)
