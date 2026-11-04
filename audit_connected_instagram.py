"""Fetch profile + recent media for the Instagram account connected to this app.

This audits the authenticated account only; it does not scrape arbitrary profiles.
Requires META_IG_USER_ID and META_PAGE_ACCESS_TOKEN in .env.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
import os

load_dotenv()
VERSION = os.getenv("META_API_VERSION", "v26.0")
IG_ID = os.getenv("META_IG_USER_ID", "")
TOKEN = os.getenv("META_PAGE_ACCESS_TOKEN", "")


def get(path: str, params: dict):
    response = requests.get(
        f"https://graph.facebook.com/{VERSION}/{path}",
        params={**params, "access_token": TOKEN},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(payload["error"])
    return payload


def main():
    if not IG_ID or not TOKEN:
        raise SystemExit("Set META_IG_USER_ID and META_PAGE_ACCESS_TOKEN in .env first")

    profile = get(IG_ID, {"fields": "id,username,name,biography,website,followers_count,follows_count,media_count,profile_picture_url"})
    media = get(f"{IG_ID}/media", {
        "fields": "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count,thumbnail_url,media_url",
        "limit": 50,
    })
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "recent_media": media.get("data", []),
        "paging": media.get("paging", {}),
        "note": "Insights are private and must be fetched separately with instagram_manage_insights permission.",
    }
    out = Path("profile/connected_account_audit.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {out} ({len(report['recent_media'])} recent items)")


if __name__ == "__main__":
    main()
