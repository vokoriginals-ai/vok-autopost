"""Publish a finished post image + caption to the VOK Facebook Page and
Instagram account through Meta's official Graph API.

Standard library only. Needs META_PAGE_TOKEN (the Vok Page token).

Flow:
1. Upload the image to the Facebook Page as a photo post (with caption).
2. Read back the public image URL Facebook gives that photo.
3. Give that URL to Instagram, wait until it's processed, then publish.
"""

from __future__ import annotations

import os
import time

from vok import net

GRAPH = "https://graph.facebook.com/v27.0"
PAGE_ID = "790959357430859"          # Facebook Page: Vok
IG_ID = "17841476806036960"          # Instagram: @vokoriginals


class PublishError(RuntimeError):
    pass


def _token() -> str:
    tok = os.environ.get("META_PAGE_TOKEN", "").strip()
    if not tok:
        raise PublishError("META_PAGE_TOKEN is not set (GitHub → Settings → Secrets).")
    return tok


def _call(fn, *args, **kw) -> dict:
    try:
        data = fn(*args, **kw)
    except net.HTTPError as e:
        raise PublishError(f"Meta API: {e}") from None
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        raise PublishError(f"Meta API error {err.get('code')}: {err.get('message')}")
    return data


def post_facebook(image_path: str, caption: str, published: bool = True) -> dict:
    """Upload to the Page. With published=False the photo stays hidden and is
    only used to get a public image link for Instagram."""
    with open(image_path, "rb") as fh:
        img = fh.read()
    data = _call(net.post_multipart, f"{GRAPH}/{PAGE_ID}/photos",
                 {"caption": caption, "published": "true" if published else "false",
                  "access_token": _token()},
                 {"source": ("post.jpg", img, "image/jpeg")})
    photo_id = data["id"]
    info = _call(net.get_json, f"{GRAPH}/{photo_id}",
                 {"fields": "images,link", "access_token": _token()})
    biggest = max(info["images"], key=lambda im: im["width"])
    return {"photo_id": photo_id, "post_id": data.get("post_id"),
            "permalink": info.get("link"), "image_url": biggest["source"]}


def post_instagram(image_url: str, caption: str) -> dict:
    tok = _token()
    container = _call(net.post_form, f"{GRAPH}/{IG_ID}/media",
                      {"image_url": image_url, "caption": caption, "access_token": tok})["id"]
    for _ in range(30):                       # wait up to ~2.5 min
        status = _call(net.get_json, f"{GRAPH}/{container}",
                       {"fields": "status_code", "access_token": tok}).get("status_code")
        if status == "FINISHED":
            break
        if status in {"ERROR", "EXPIRED"}:
            raise PublishError(f"Instagram could not process the image (status {status}).")
        time.sleep(5)
    else:
        raise PublishError("Instagram took too long to process the image.")
    media_id = _call(net.post_form, f"{GRAPH}/{IG_ID}/media_publish",
                     {"creation_id": container, "access_token": tok})["id"]
    link = _call(net.get_json, f"{GRAPH}/{media_id}",
                 {"fields": "permalink", "access_token": tok}).get("permalink")
    return {"media_id": media_id, "permalink": link}


def host_image(image_path: str) -> str | None:
    """Hidden (unpublished) upload to the Page, just to get a public image link
    for the approval email. Nothing appears on the Page."""
    try:
        return post_facebook(image_path, "", published=False)["image_url"]
    except PublishError as e:
        print(f"could not host preview image: {e}")
        return None


def publish(image_path: str, caption: str, targets=("facebook", "instagram"),
            done: dict | None = None, on_step=None) -> dict:
    """Publish to each target that isn't already in `done`.

    `on_step(result)` is called after each platform succeeds, so progress is
    saved even if a later step fails (a re-run then never double-posts).
    """
    result: dict = dict(done or {})
    image_url = (result.get("facebook") or {}).get("image_url")

    if "facebook" in targets and "facebook" not in result:
        fb = post_facebook(image_path, caption, published=True)
        result["facebook"] = fb
        image_url = fb["image_url"]
        if on_step:
            on_step(result)

    if "instagram" in targets and "instagram" not in result:
        if not image_url:  # Facebook not wanted/done: hidden upload just to host the image
            image_url = post_facebook(image_path, caption, published=False)["image_url"]
        result["instagram"] = post_instagram(image_url, caption)
        if on_step:
            on_step(result)
    return result


def recent_vok_posts(hours: int = 24) -> list[list[str]]:
    """Keywords of everything posted on VOK recently, by this system or by staff,
    so the same story isn't posted twice."""
    from datetime import datetime, timedelta, timezone
    from vok.collect import _words
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    texts = []
    ig = net.get_json(f"{GRAPH}/{IG_ID}/media", {"fields": "caption,timestamp", "limit": 50,
                                                  "access_token": _token()})
    for m in ig.get("data", []):
        if datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z") >= cutoff:
            texts.append(m.get("caption") or "")
    fb = net.get_json(f"{GRAPH}/{PAGE_ID}/posts", {"fields": "message,created_time", "limit": 50,
                                                    "access_token": _token()})
    for m in fb.get("data", []):
        if datetime.strptime(m["created_time"], "%Y-%m-%dT%H:%M:%S%z") >= cutoff:
            texts.append(m.get("message") or "")
    out = []
    for t in texts:
        first = " ".join(t.strip().splitlines()[:3])[:300]      # headline-ish part
        if first:
            out.append(sorted(_words(first)))
    print(f"VOK posted {len(out)} items in the last {hours}h (skipping those stories)")
    return out
