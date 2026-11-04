import time
from urllib.parse import urlparse
import requests
from app.config import settings
from app.models import ContentFormat


class InstagramAPIError(RuntimeError):
    pass


class InstagramPublisher:
    def __init__(self):
        if not settings.meta_ig_user_id or not settings.meta_page_access_token:
            raise RuntimeError("Не заданы META_IG_USER_ID и META_PAGE_ACCESS_TOKEN в .env")
        self.base_url = f"https://graph.facebook.com/{settings.meta_api_version}"
        self.ig_user_id = settings.meta_ig_user_id
        self.token = settings.meta_page_access_token

    def _request(self, method: str, path: str, data: dict | None = None) -> dict:
        url = f"{self.base_url}/{path.lstrip('/')}"
        payload = dict(data or {})
        payload["access_token"] = self.token
        try:
            if method.upper() == "GET":
                response = requests.request(method, url, params=payload, timeout=45)
            else:
                response = requests.request(method, url, data=payload, timeout=45)
        except requests.RequestException as exc:
            raise InstagramAPIError(f"Ошибка сети при обращении к Meta: {exc}") from exc
        try:
            result = response.json()
        except ValueError as exc:
            raise InstagramAPIError(f"Meta вернула не-JSON ответ ({response.status_code})") from exc
        if not response.ok or "error" in result:
            error = result.get("error", result)
            message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            code = error.get("code") if isinstance(error, dict) else None
            raise InstagramAPIError(f"Meta API error {code}: {message}")
        return result

    @staticmethod
    def _validate_public_url(media_url: str) -> None:
        parsed = urlparse(media_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"Meta должна иметь доступ к HTTPS URL: {media_url}")

    def _create_container(self, params: dict) -> str:
        result = self._request("POST", f"/{self.ig_user_id}/media", params)
        container_id = result.get("id")
        if not container_id:
            raise InstagramAPIError(f"Meta не вернула ID контейнера: {result}")
        return str(container_id)

    def _wait_until_ready(self, container_id: str) -> None:
        deadline = time.monotonic() + settings.container_timeout_seconds
        while time.monotonic() < deadline:
            result = self._request("GET", f"/{container_id}", {"fields": "status_code,status"})
            status = result.get("status_code")
            if status in {"FINISHED", "PUBLISHED"}:
                return
            if status in {"ERROR", "EXPIRED"}:
                raise InstagramAPIError(f"Контейнер {container_id}: {status} — {result.get('status', '')}")
            time.sleep(8)
        raise TimeoutError(f"Instagram не завершил обработку контейнера {container_id} вовремя")

    def _publish_container(self, container_id: str) -> str:
        result = self._request(
            "POST",
            f"/{self.ig_user_id}/media_publish",
            {"creation_id": container_id},
        )
        media_id = result.get("id")
        if not media_id:
            raise InstagramAPIError(f"Meta не вернула ID опубликованного медиа: {result}")
        return str(media_id)

    def publish(self, content_format: ContentFormat, media_urls: list[str], caption: str = "") -> str:
        if not media_urls:
            raise ValueError("Нет медиафайла. Добавь изображение или видео перед публикацией.")
        for url in media_urls:
            self._validate_public_url(url)

        if content_format == ContentFormat.CAROUSEL:
            if not 2 <= len(media_urls) <= 10:
                raise ValueError("Карусель Instagram должна содержать от 2 до 10 элементов.")
            child_ids = []
            for url in media_urls:
                child_id = self._create_container({"image_url": url, "is_carousel_item": "true"})
                self._wait_until_ready(child_id)
                child_ids.append(child_id)
            parent_id = self._create_container({
                "media_type": "CAROUSEL",
                "children": ",".join(child_ids),
                "caption": caption[:2200],
            })
            self._wait_until_ready(parent_id)
            return self._publish_container(parent_id)

        media_url = media_urls[0]
        is_video = urlparse(media_url).path.lower().endswith((".mp4", ".mov", ".m4v"))

        if content_format == ContentFormat.POST:
            if is_video:
                raise ValueError("Для формата POST нужен JPEG. Видео публикуй как REEL.")
            params = {"image_url": media_url, "caption": caption[:2200]}
        elif content_format == ContentFormat.REEL:
            if not is_video:
                raise ValueError("Для Reels нужен загруженный MP4/MOV ролик.")
            params = {
                "media_type": "REELS",
                "video_url": media_url,
                "caption": caption[:2200],
                "share_to_feed": "true",
            }
        elif content_format == ContentFormat.STORY:
            params = {"media_type": "STORIES", "video_url" if is_video else "image_url": media_url}
        else:
            raise ValueError(f"Неподдерживаемый формат: {content_format}")

        container_id = self._create_container(params)
        self._wait_until_ready(container_id)
        return self._publish_container(container_id)

    def get_media_insights(self, media_id: str) -> dict:
        result = self._request(
            "GET",
            f"/{media_id}/insights",
            {"metric": "views,reach,total_interactions"},
        )
        metrics = {}
        for row in result.get("data", []):
            name = row.get("name")
            value = None
            if row.get("values"):
                value = row["values"][0].get("value")
            elif isinstance(row.get("total_value"), dict):
                value = row["total_value"].get("value")
            if name and value is not None:
                metrics[name] = value
        return metrics
