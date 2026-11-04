"""Optional Runway adapter for generating a vertical multi-shot Reel."""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import requests

from app.config import settings
from app.services.media import MEDIA_PATH, _normalise_video, public_url

API_BASE = "https://api.dev.runwayml.com/v1"
API_VERSION_HEADER = "2024-11-06"


class RunwayAPIError(RuntimeError):
    pass


def _build_story_prompt(payload: dict) -> str:
    hook = str(payload.get("hook", "A useful business insight"))
    voiceover = str(payload.get("voiceover", ""))
    cta = str(payload.get("cta", ""))
    scenes = payload.get("scenes", [])
    scene_lines = []
    for index, scene in enumerate(scenes[:5], start=1):
        visual = str(scene.get("visual_action", ""))
        on_screen = str(scene.get("on_screen_text", ""))
        if visual or on_screen:
            scene_lines.append(f"Shot {index}: {visual}. On-screen concept: {on_screen}.")
    scene_text = "\n".join(scene_lines)
    prompt = (
        "Create a premium vertical 9:16 short-form business Instagram Reel, exactly five "
        "coherent cinematic shots, polished commercial look, realistic people and objects, "
        "natural camera motion, clean composition, professional soft lighting. "
        "No visible logos, no watermarks, no gibberish text, no subtitles baked into frames. "
        "Use tasteful ambient sound only; do not invent spoken claims.\n"
        f"Opening hook concept: {hook}.\n"
        f"Shot plan:\n{scene_text}\n"
        f"Narrative context (for visual guidance only): {voiceover[:700]}\n"
        f"Closing visual should support this CTA: {cta}."
    )
    return prompt[:2450]


def generate_runway_video(payload: dict) -> str:
    """Generate, immediately download, and normalize a vertical MP4 to local media."""
    if not settings.runway_api_key:
        raise RuntimeError("Не задан RUNWAY_API_KEY")

    duration = max(5, min(int(settings.runway_video_duration), 15))
    if duration not in (5, 10, 15):
        duration = 15

    headers = {
        "Authorization": f"Bearer {settings.runway_api_key}",
        "X-Runway-Version": API_VERSION_HEADER,
        "Content-Type": "application/json",
    }
    body = {
        "mode": "auto",
        "version": settings.runway_recipe_version,
        "prompt": _build_story_prompt(payload),
        "ratio": "720:1280",
        "duration": duration,
        "audio": True,
    }

    try:
        created = requests.post(
            f"{API_BASE}/recipes/multi_shot_video",
            headers=headers,
            json=body,
            timeout=60,
        )
        created.raise_for_status()
        task_id = created.json().get("id")
        if not task_id:
            raise RunwayAPIError(f"Runway не вернул ID задачи: {created.text[:1000]}")

        deadline = time.monotonic() + 20 * 60
        task = {}
        while time.monotonic() < deadline:
            response = requests.get(
                f"{API_BASE}/tasks/{task_id}",
                headers=headers,
                timeout=45,
            )
            response.raise_for_status()
            task = response.json()
            status = task.get("status")
            if status == "SUCCEEDED":
                break
            if status in {"FAILED", "CANCELED", "CANCELLED"}:
                raise RunwayAPIError(
                    f"Runway generation {status}: {task.get('failure', task.get('error', 'unknown error'))}"
                )
            time.sleep(10)
        else:
            raise TimeoutError(f"Runway generation timed out; task_id={task_id}")

        outputs = task.get("output") or []
        if not outputs or not str(outputs[0]).startswith("https://"):
            raise RunwayAPIError(f"Runway task succeeded without a downloadable HTTPS output: {task}")

        raw_path = MEDIA_PATH / f"runway_raw_{uuid.uuid4().hex}.mp4"
        final_path = MEDIA_PATH / f"reel_{uuid.uuid4().hex}.mp4"
        with requests.get(outputs[0], stream=True, timeout=(30, 300)) as download:
            download.raise_for_status()
            with raw_path.open("wb") as target:
                for chunk in download.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        target.write(chunk)
        _normalise_video(raw_path, final_path)
        return public_url(final_path.name)
    except requests.RequestException as exc:
        raise RunwayAPIError(f"Сетевая ошибка Runway: {exc}") from exc
