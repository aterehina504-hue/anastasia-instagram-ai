import json
import re
from app.config import settings
from app.models import ContentFormat


FORMAT_INSTRUCTIONS = {
    ContentFormat.POST: "Сделай один пост с сильным первым предложением, полезной сутью и CTA. Верни visual_prompt и alt_text.",
    ContentFormat.CAROUSEL: "Создай карусель ровно из 5 слайдов. У каждого слайда короткий headline (до 8 слов), body (до 25 слов) и visual_prompt. Слайды должны логично вести читателя от проблемы к решению. Верни caption.",
    ContentFormat.REEL: "Создай сценарий Reels на 20-35 секунд: hook, 4-6 сцен с текстом/действием, voiceover, финальный CTA и caption. Видео будет загружено отдельно человеком или внешним видеогенератором.",
    ContentFormat.STORY: "Создай одну Stories-публикацию: короткий заголовок до 8 слов, supporting_text до 20 слов, CTA, visual_prompt и caption для внутреннего использования. Не рассчитывай, что caption будет виден в Stories.",
}


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise ValueError("AI returned invalid JSON")


def generate_content(
    topic: str,
    content_format: ContentFormat,
    brand_name: str,
    industry: str,
    audience: str,
    tone: str,
    offer: str,
    language: str = "Russian",
) -> dict:
    if not settings.openai_api_key:
        raise RuntimeError("Не задан OPENAI_API_KEY в .env")

    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    schema = {
        "topic": topic,
        "format": content_format.value,
        "brand_name": brand_name,
        "industry": industry,
        "audience": audience,
        "tone": tone,
        "offer": offer,
        "language": language,
        "format_requirements": FORMAT_INSTRUCTIONS[content_format],
    }
    prompt = f"""
Ты — редактор и контент-стратег авторского Instagram-профиля контент-креатора. Пиши от первого лица автора, если формат этого требует. Не превращай личный бренд в безликий корпоративный аккаунт.
Создай качественный, конкретный и естественный материал на языке {language}.
Используй только факты, которые даны во входных данных. Не выдумывай цены,
статистику, сертификаты, результаты, отзывы, гарантии или характеристики продукта.
Если фактов не хватает, формулируй без неподтверждённых утверждений.
Не используй кликбейт, искусственную срочность или чрезмерные хештеги.
Хештеги: максимум 5, только релевантные.

ВХОДНЫЕ ДАННЫЕ:
{json.dumps(schema, ensure_ascii=False, indent=2)}

ТРЕБОВАНИЯ К ФОРМАТУ:
{FORMAT_INSTRUCTIONS[content_format]}

Верни только валидный JSON-объект. Общие поля: caption (строка), hashtags (массив строк),
content_rationale (короткое пояснение для редактора). Форматные поля — по инструкции выше.
Для CAROUSEL: slides — массив ровно из 5 объектов с headline, body, visual_prompt.
Для REEL: hook, scenes (массив объектов с duration_seconds, visual_action, on_screen_text, voiceover),
voiceover, cta.
Для STORY: headline, supporting_text, cta, visual_prompt.
Для POST: visual_prompt, alt_text.
Для visual_prompt всегда попроси создать фотореалистичный или иллюстративный фон без букв,
логотипов, псевдотекста и водяных знаков, с чистым местом под графический текст.
"""
    response = client.responses.create(
        model=settings.openai_text_model,
        input=prompt,
        text={"format": {"type": "json_object"}},
    )
    data = _extract_json(response.output_text)
    data.setdefault("caption", "")
    data.setdefault("hashtags", [])
    if data["hashtags"]:
        tags = [t if str(t).startswith("#") else f"#{t}" for t in data["hashtags"]]
        data["hashtags"] = tags[:5]
        if content_format != ContentFormat.STORY:
            data["caption"] = (data["caption"].strip() + "\n\n" + " ".join(tags[:5])).strip()
    return data


def generate_daily_topics(count: int, brand_name: str, industry: str, audience: str, tone: str, offer: str, allowed_formats: list[str]) -> list[dict]:
    """Generate evergreen topics and a format mix for today's editorial queue."""
    if not settings.openai_api_key:
        raise RuntimeError("Не задан OPENAI_API_KEY в .env")
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    prompt = f"""
Составь контент-план на сегодня для авторского Instagram-профиля контент-креатора. Балансируй экспертность, портфолио, закулисье, вовлечение и мягкое предложение услуг. Не выдумывай нишу, биографию или коммерческие результаты.
Верни ровно {count} разных идей. Они должны быть полезны аудитории и не повторять друг друга.
Не выдумывай факты, кейсы, цифры или преимущества. Используй только описание бизнеса ниже.
Для каждой идеи выбери format ТОЛЬКО из: {allowed_formats}.
Разнообразь задачу: экспертность, разбор ошибки, процесс, вопрос аудитории, продукт без агрессивной продажи.

Бренд: {brand_name}
Отрасль: {industry}
Аудитория: {audience}
Тон: {tone}
Проверенный оффер/факты: {offer}

Верни только JSON: {{"items": [{{"topic": "...", "format": "POST|CAROUSEL|REEL|STORY"}}]}}
"""
    response = client.responses.create(
        model=settings.openai_text_model,
        input=prompt,
        text={"format": {"type": "json_object"}},
    )
    data = _extract_json(response.output_text)
    items = data.get("items", [])
    allowed = set(allowed_formats)
    cleaned = []
    for item in items:
        fmt = str(item.get("format", "POST")).upper()
        topic = str(item.get("topic", "")).strip()
        if topic and fmt in allowed:
            cleaned.append({"topic": topic[:500], "format": fmt})
        if len(cleaned) == count:
            break
    if len(cleaned) != count:
        raise ValueError(f"AI вернула {len(cleaned)} тем вместо {count}")
    return cleaned
