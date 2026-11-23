"""Publish a finished post image + caption to the VOK Facebook Page and
Instagram account through Meta's official Graph API.

Needs one secret in the environment: META_PAGE_TOKEN (the Vok Page token).

Flow:
1. Upload the image to the Facebook Page as a photo post (with caption).
2. Read back the public image URL Facebook gives that photo.
3. Give that URL to Instagram, wait until it's processed, then publish.
"""

from __future__ import annotations

import os
import time

import requests

GRAPH = "https://graph.facebook.com/v27.0"
PAGE_ID = "790959357430859"          # Facebook Page: Vok
IG_ID = "17841476806036960"          # Instagram: @vokoriginals


class PublishError(RuntimeError):
    pass


def _token() -> str:
    tok = os.environ.get("META_PAGE_TOKEN", "").strip()
    if not tok:
        raise PublishError("META_PAGE_TOKEN is not set (add it in GitHub → Settings → Secrets).")
    return tok


def _check(r: requests.Response) -> dict:
    try:
        data = r.json()
    except ValueError:
        raise PublishError(f"HTTP {r.status_code}: {r.text[:300]}")
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", {})
        raise PublishError(f"Meta API error {err.get('code')}: {err.get('message')}")
    return data


def post_facebook(image_path: str, caption: str, published: bool = True) -> dict:
    """Upload to the Page. With published=False the photo stays hidden and is
    only used to get a public image link for Instagram."""
    with open(image_path, "rb") as fh:
        r = requests.post(
            f"{GRAPH}/{PAGE_ID}/photos",
            data={"caption": caption, "published": "true" if published else "false",
                  "access_token": _token()},
            files={"source": fh},
            timeout=120,
        )
    data = _check(r)
    photo_id = data["id"]
    info = _check(requests.get(
        f"{GRAPH}/{photo_id}",
        params={"fields": "images,link", "access_token": _token()},
        timeout=60,
    ))
    biggest = max(info["images"], key=lambda im: im["width"])
    return {
        "photo_id": photo_id,
        "post_id": data.get("post_id"),
        "permalink": info.get("link"),
        "image_url": biggest["source"],
    }


def post_instagram(image_url: str, caption: str) -> dict:
    tok = _token()
    container = _check(requests.post(
        f"{GRAPH}/{IG_ID}/media",
        data={"image_url": image_url, "caption": caption, "access_token": tok},
        timeout=120,
    ))["id"]

    for _ in range(30):                       # wait up to ~2.5 min
        status = _check(requests.get(
            f"{GRAPH}/{container}",
            params={"fields": "status_code", "access_token": tok},
            timeout=60,
        )).get("status_code")
        if status == "FINISHED":
            break
        if status in {"ERROR", "EXPIRED"}:
            raise PublishError(f"Instagram could not process the image (status {status}).")
        time.sleep(5)
    else:
        raise PublishError("Instagram took too long to process the image.")

    media_id = _check(requests.post(
        f"{GRAPH}/{IG_ID}/media_publish",
        data={"creation_id": container, "access_token": tok},
        timeout=120,
    ))["id"]
    link = _check(requests.get(
        f"{GRAPH}/{media_id}",
        params={"fields": "permalink", "access_token": tok},
        timeout=60,
    )).get("permalink")
    return {"media_id": media_id, "permalink": link}


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
