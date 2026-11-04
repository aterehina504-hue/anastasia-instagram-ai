from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_timezone: str = "Europe/Paris"
    admin_username: str = "admin"
    admin_password: str = "change-me"

    public_base_url: str = "https://your-public-domain.example"
    media_dir: str = "/data/media"
    font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    openai_api_key: str = ""
    openai_text_model: str = "gpt-6-luna"
    openai_image_model: str = "gpt-image-2.5-flare"
    generate_visuals: bool = True

    runway_api_key: str = ""
    runway_recipe_version: str = "2026-06"
    runway_video_duration: int = 15

    meta_api_version: str = "v26.0"
    meta_ig_user_id: str = ""
    meta_page_access_token: str = ""

    database_url: str = "sqlite:///./instagram_ai.db"
    scheduler_interval_seconds: int = 30
    container_timeout_seconds: int = 300
    max_upload_mb: int = 400

    # Daily AI planning is opt-in: generated drafts still require manual approval.
    daily_drafts_enabled: bool = False
    daily_draft_count: int = 2
    daily_generation_hour: int = 6
    daily_generation_minute: int = 0
    brand_name: str = "Anastasia | content creator"
    brand_industry: str = "Контент-креатор; специализацию уточнить по реальной ленте"
    brand_audience: str = "Подписчики и потенциальные заказчики; сегменты аудитории требуют подтверждения"
    brand_tone: str = "Живой, визуальный, уверенный, дружелюбный, авторский"
    brand_offer: str = "Не заполнено: не придумывать услуги, цены, кейсы или результаты"
    daily_formats: str = "CAROUSEL,REEL,POST,STORY"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
