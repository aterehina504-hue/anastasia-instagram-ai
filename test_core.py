import pytest
from app.models import ContentFormat
from app.services.ai import _extract_json
from app.services.instagram import InstagramPublisher


def test_extract_json_plain_and_fenced():
    assert _extract_json('{"caption":"тест"}') == {"caption": "тест"}
    assert _extract_json('```json\n{"caption":"тест"}\n```') == {"caption": "тест"}


def test_format_enum_contains_all_required_types():
    assert {x.value for x in ContentFormat} == {"POST", "CAROUSEL", "REEL", "STORY"}


def test_meta_public_url_must_be_https():
    with pytest.raises(ValueError):
        InstagramPublisher._validate_public_url("http://localhost/test.jpg")
    InstagramPublisher._validate_public_url("https://media.example.com/test.jpg")


def test_runway_prompt_uses_reel_scene_plan():
    from app.services.runway import _build_story_prompt

    prompt = _build_story_prompt({
        "hook": "Три ошибки в продажах",
        "voiceover": "Не делайте эти ошибки",
        "cta": "Сохраните пост",
        "scenes": [
            {"visual_action": "Менеджер смотрит на пустую CRM", "on_screen_text": "Нет системы"}
        ],
    })
    assert "Три ошибки в продажах" in prompt
    assert "Менеджер смотрит на пустую CRM" in prompt
    assert "vertical 9:16" in prompt
