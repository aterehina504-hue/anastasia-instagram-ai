import base64
import logging
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import BinaryIO
from PIL import Image, ImageDraw, ImageFont, ImageOps
from app.config import settings
from app.models import ContentFormat


logger = logging.getLogger(__name__)
MEDIA_PATH = Path(settings.media_dir)
MEDIA_PATH.mkdir(parents=True, exist_ok=True)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(settings.font_path, size=size)
    except OSError:
        return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = str(text).split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _render_text_overlay(image_path: Path, title: str, body: str = "", footer: str = "") -> None:
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    band_top = int(height * 0.57)
    draw_overlay.rounded_rectangle(
        (int(width * 0.045), band_top, int(width * 0.955), int(height * 0.94)),
        radius=28,
        fill=(10, 15, 25, 205),
    )
    image = Image.alpha_composite(image.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(image)
    title_font = _font(max(34, int(width * 0.060)))
    body_font = _font(max(22, int(width * 0.033)))
    footer_font = _font(max(18, int(width * 0.022)))
    x = int(width * 0.09)
    y = band_top + int(height * 0.055)
    max_w = int(width * 0.80)
    for line in _wrap_text(draw, title, title_font, max_w)[:3]:
        draw.text((x, y), line, font=title_font, fill=(255, 255, 255, 255))
        y += int(title_font.size * 1.18)
    y += int(height * 0.015)
    for line in _wrap_text(draw, body, body_font, max_w)[:4]:
        draw.text((x, y), line, font=body_font, fill=(235, 239, 245, 255))
        y += int(body_font.size * 1.35)
    if footer:
        draw.text((x, int(height * 0.90)), footer[:70], font=footer_font, fill=(190, 205, 225, 255))
    image.convert("RGB").save(image_path, "JPEG", quality=90, optimize=True)


def generate_image(prompt: str, size: str, output_name: str) -> str:
    if not settings.openai_api_key:
        raise RuntimeError("Не задан OPENAI_API_KEY в .env")
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    result = client.images.generate(
        model=settings.openai_image_model,
        prompt=prompt,
        size=size,
        quality="medium",
        output_format="jpeg",
        n=1,
    )
    image_bytes = base64.b64decode(result.data[0].b64_json)
    target = MEDIA_PATH / output_name
    target.write_bytes(image_bytes)
    # Normalise image to RGB JPEG, which is the safest input for Instagram publishing.
    with Image.open(target) as image:
        image.convert("RGB").save(target, "JPEG", quality=90, optimize=True)
    return public_url(target.name)


def public_url(filename: str) -> str:
    if not settings.public_base_url.startswith("https://"):
        raise RuntimeError("PUBLIC_BASE_URL должен быть публичным HTTPS URL, доступным серверам Meta")
    return f"{settings.public_base_url.rstrip('/')}/media/{filename}"


def create_ai_assets(content_format: ContentFormat, payload: dict, brand_name: str) -> list[str]:
    should_generate_runway = content_format == ContentFormat.REEL and bool(settings.runway_api_key)
    if not settings.generate_visuals and not should_generate_runway:
        return []
    urls: list[str] = []
    if content_format == ContentFormat.POST:
        name = f"{uuid.uuid4().hex}.jpg"
        url = generate_image(payload.get("visual_prompt", "Editorial business Instagram visual, no text"), "1024x1280", name)
        urls.append(url)
    elif content_format == ContentFormat.STORY:
        name = f"{uuid.uuid4().hex}.jpg"
        url = generate_image(payload.get("visual_prompt", "Vertical editorial business Story background, no text"), "1024x1792", name)
        path = MEDIA_PATH / name
        _render_text_overlay(path, payload.get("headline", ""), payload.get("supporting_text", ""), payload.get("cta", brand_name))
        urls.append(public_url(name))
    elif content_format == ContentFormat.CAROUSEL:
        slides = payload.get("slides", [])[:10]
        if not 2 <= len(slides) <= 10:
            raise ValueError("AI должна вернуть от 2 до 10 слайдов карусели")
        for index, slide in enumerate(slides, start=1):
            name = f"{uuid.uuid4().hex}.jpg"
            prompt = slide.get("visual_prompt", "Clean editorial business background")
            url = generate_image(prompt, "1024x1280", name)
            path = MEDIA_PATH / name
            _render_text_overlay(path, slide.get("headline", ""), slide.get("body", ""), f"{brand_name}  ·  {index}/{len(slides)}")
            urls.append(url)
    elif content_format == ContentFormat.REEL and settings.runway_api_key:
        # Optional automated video generation. A provider failure must not discard
        # the AI script: keep the draft and let the operator upload an MP4 instead.
        from app.services.runway import generate_runway_video
        try:
            urls.append(generate_runway_video(payload))
        except Exception as exc:
            logger.exception("Runway video generation failed; keeping script-only draft")
            payload["video_generation_error"] = str(exc)[:1000]
    # Without a Runway API key, Reels remain a script-only draft until an MP4 is uploaded.
    return urls


def _normalise_video(raw_path: Path, output_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raw_path.unlink(missing_ok=True)
        raise RuntimeError("FFmpeg не найден. Установи FFmpeg или используй Docker-образ проекта.")
    command = [
        ffmpeg, "-y", "-i", str(raw_path),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
        "-r", "30", "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-preset", "medium", "-crf", "21", "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-movflags", "+faststart", str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    raw_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(f"Ошибка FFmpeg: {completed.stderr[-1200:]}")


def save_uploaded_file(file: BinaryIO, original_name: str, content_format: ContentFormat) -> str:
    suffix = Path(original_name).suffix.lower()
    allowed_images = {".jpg", ".jpeg", ".png", ".webp"}
    allowed_videos = {".mp4", ".mov", ".m4v"}

    is_video_upload = suffix in allowed_videos
    if content_format == ContentFormat.REEL and not is_video_upload:
        raise ValueError("Для Reels загрузи видео MP4 или MOV")
    if content_format == ContentFormat.STORY and suffix not in (allowed_images | allowed_videos):
        raise ValueError("Для Stories загрузи изображение или видео MP4/MOV")
    if content_format in {ContentFormat.POST, ContentFormat.CAROUSEL} and suffix not in allowed_images:
        raise ValueError("Для поста или карусели загрузи JPG, JPEG, PNG или WEBP")

    raw_name = f"upload_{uuid.uuid4().hex}{suffix}"
    raw_path = MEDIA_PATH / raw_name
    with raw_path.open("wb") as destination:
        shutil.copyfileobj(file, destination)

    if is_video_upload:
        output_name = f"video_{uuid.uuid4().hex}.mp4"
        output_path = MEDIA_PATH / output_name
        _normalise_video(raw_path, output_path)
        return public_url(output_name)

    output_name = f"upload_{uuid.uuid4().hex}.jpg"
    output_path = MEDIA_PATH / output_name
    with Image.open(raw_path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        if content_format == ContentFormat.STORY:
            image = ImageOps.fit(image, (1080, 1920), method=Image.Resampling.LANCZOS)
        else:
            image = ImageOps.fit(image, (1080, 1350), method=Image.Resampling.LANCZOS)
        image.save(output_path, "JPEG", quality=90, optimize=True)
    raw_path.unlink(missing_ok=True)
    return public_url(output_name)
