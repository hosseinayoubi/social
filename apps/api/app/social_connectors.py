"""Social platform connectors.

This file is intentionally conservative: it provides a safe structure and
*optional* integrations. For production, prefer official APIs and business integrations.

- Instagram: instagrapi is not an official public API. Use at your own risk.
- Facebook: uses Graph API via HTTP calls (token required).

If creds aren't configured, collector returns empty.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
import os, tempfile
import httpx

from .settings import settings

@dataclass
class CollectedPost:
    platform: str
    original_url: str
    original_id: str | None
    caption: str | None
    media_type: str  # photo|video
    media_url: str | None
    posted_at: datetime | None
    engagement: int

async def collect_instagram(username: str, limit: int = 25) -> List[CollectedPost]:
    # Optional. Requires instagrapi installed and credentials set.
    if not settings.INSTAGRAM_USERNAME or not settings.INSTAGRAM_PASSWORD:
        return []
    try:
        from instagrapi import Client  # type: ignore
    except Exception:
        return []

    cl = Client()
    cl.login(settings.INSTAGRAM_USERNAME, settings.INSTAGRAM_PASSWORD)
    user_id = cl.user_id_from_username(username)
    medias = cl.user_medias(user_id, amount=limit)

    out: List[CollectedPost] = []
    for m in medias:
        likes = int(getattr(m, "like_count", 0) or 0)
        comments = int(getattr(m, "comment_count", 0) or 0)
        engagement = likes + comments * 3
        media_type = "video" if str(getattr(m, "media_type", "")) in ["2", "3"] else "photo"
        media_url = None
        try:
            if media_type == "video":
                media_url = getattr(m, "video_url", None)
            else:
                media_url = getattr(m, "thumbnail_url", None) or getattr(m, "url", None)
        except Exception:
            media_url = None
        out.append(
            CollectedPost(
                platform="instagram",
                original_url=f"https://www.instagram.com/p/{m.code}/",
                original_id=str(m.id),
                caption=getattr(m, "caption_text", None),
                media_type=media_type,
                media_url=media_url,
                posted_at=getattr(m, "taken_at", None),
                engagement=engagement,
            )
        )
    return out

async def collect_facebook(page_name: str, limit: int = 25) -> List[CollectedPost]:
    if not settings.FACEBOOK_PAGE_TOKEN:
        return []
    token = settings.FACEBOOK_PAGE_TOKEN
    async with httpx.AsyncClient(timeout=30) as client:
        # Find page
        search = await client.get(
            "https://graph.facebook.com/v19.0/search",
            params={"type": "page", "q": page_name, "access_token": token},
        )
        search.raise_for_status()
        data = search.json().get("data", [])
        if not data:
            return []
        page_id = data[0]["id"]

        posts = await client.get(
            f"https://graph.facebook.com/v19.0/{page_id}/posts",
            params={
                "fields": "id,message,created_time,permalink_url,shares.summary(true),"
                         "likes.summary(true),comments.summary(true),attachments",
                "limit": limit,
                "access_token": token,
            },
        )
        posts.raise_for_status()
        items = posts.json().get("data", [])

    out: List[CollectedPost] = []
    for p in items:
        likes = int((p.get("likes") or {}).get("summary", {}).get("total_count", 0) or 0)
        comments = int((p.get("comments") or {}).get("summary", {}).get("total_count", 0) or 0)
        shares = int((p.get("shares") or {}).get("count", 0) or 0)
        engagement = likes + comments * 3 + shares * 5

        media_url = None
        media_type = "photo"
        try:
            att = (p.get("attachments") or {}).get("data", [])
            if att:
                a0 = att[0]
                # attempt to detect video/photo
                t = (a0.get("type") or "").lower()
                if "video" in t:
                    media_type = "video"
                media_url = (((a0.get("media") or {}).get("image") or {}).get("src"))
        except Exception:
            pass

        out.append(
            CollectedPost(
                platform="facebook",
                original_url=p.get("permalink_url") or f"https://facebook.com/{p.get('id')}",
                original_id=p.get("id"),
                caption=p.get("message"),
                media_type=media_type,
                media_url=media_url,
                posted_at=None,
                engagement=engagement,
            )
        )
    return out

async def download_to_temp(url: str, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
    return path

async def publish_instagram(media_path: str, media_type: str, caption: str) -> dict:
    if not settings.INSTAGRAM_USERNAME or not settings.INSTAGRAM_PASSWORD:
        raise RuntimeError("Instagram credentials not configured")
    try:
        from instagrapi import Client  # type: ignore
    except Exception as e:
        raise RuntimeError("instagrapi not installed") from e
    cl = Client()
    cl.login(settings.INSTAGRAM_USERNAME, settings.INSTAGRAM_PASSWORD)
    if media_type == "video":
        res = cl.video_upload(media_path, caption)
    else:
        res = cl.photo_upload(media_path, caption)
    return {"remote_post_id": str(getattr(res, "id", "")), "remote_url": None}

async def publish_facebook(media_path: str, media_type: str, caption: str) -> dict:
    if not settings.FACEBOOK_PAGE_TOKEN or not settings.FACEBOOK_PAGE_ID:
        raise RuntimeError("Facebook page token/page id not configured")
    token = settings.FACEBOOK_PAGE_TOKEN
    page_id = settings.FACEBOOK_PAGE_ID
    async with httpx.AsyncClient(timeout=60) as client:
        if media_type == "video":
            # video upload requires /videos endpoint and multipart
            with open(media_path, "rb") as f:
                r = await client.post(
                    f"https://graph.facebook.com/v19.0/{page_id}/videos",
                    data={"description": caption, "access_token": token},
                    files={"source": f},
                )
        else:
            with open(media_path, "rb") as f:
                r = await client.post(
                    f"https://graph.facebook.com/v19.0/{page_id}/photos",
                    data={"caption": caption, "access_token": token},
                    files={"source": f},
                )
        r.raise_for_status()
        data = r.json()
    return {"remote_post_id": str(data.get("id", "")), "remote_url": None}
