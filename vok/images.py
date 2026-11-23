"""Find the best free-to-use photo for a story.

1. Collect candidates from Wikimedia Commons (real news photos of leaders,
   cities, events) and Openverse (Creative Commons photo sites).
2. Download the top few and check them: big enough, sharp (not blurry),
   not used in the last 4 days.
3. Keep the best one.

Only public-domain / CC0 / CC BY / CC BY-SA images are used, and the credit
line is returned so it can go in the caption (required by CC BY).
"""

from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

from vok import net

OK_LICENSES = re.compile(r"^(cc0|public domain|pd|cc by(-sa)?( \d\.\d)?)", re.I)
TAG_RE = re.compile(r"<[^>]+>")
SKIP_WORDS = re.compile(
    r"(logo|flag|map|coat of arms|seal|icon|diagram|chart|svg|signature|painting|engraving"
    r"|circa|(?<![a-z0-9])c\. ?\d|(?<!\d)1[5-9]\d\d(?!\d))", re.I)   # no archive/historic images
BOT_UA = "VokAutopost/1.0 (https://github.com/vokoriginals-ai/vok-autopost) news-photo-search"

# Openverse sources that are nature/science archives, not news-style photos
BAD_SOURCES = {"inaturalist", "nappy", "sketchfab", "thingiverse", "svgsilh", "phylopic",
               "europeana", "rijksmuseum", "smithsonian", "museumsvictoria", "nasa",
               "biodiversity", "met", "clevelandmuseum", "brooklynmuseum"}

MIN_SIDE = 1000          # smaller photos look soft on a 1080x1350 post
MIN_SHARPNESS = 120      # below this the photo is blurry (see sharpness())
MAX_DOWNLOADS = 6        # how many candidates to actually download and check


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s or ""))).strip()


def _commons(params: dict) -> dict:
    for attempt in range(3):
        try:
            return json.loads(net.get("https://commons.wikimedia.org/w/api.php", params,
                                      headers={"User-Agent": BOT_UA}))
        except net.HTTPError as e:
            if e.status != 429 or attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    return {}


def wikimedia(query: str) -> list[dict]:
    data = _commons({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 20,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 2000,
    })
    pages = sorted((data.get("query") or {}).get("pages", {}).values(),
                   key=lambda p: p.get("index", 99))
    out = []
    for rank, p in enumerate(pages):
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = _strip(meta.get("LicenseShortName", {}).get("value", ""))
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if not OK_LICENSES.match(lic) or SKIP_WORDS.search(p.get("title", "")):
            continue
        if min(info.get("width", 0), info.get("height", 0)) < MIN_SIDE:
            continue
        artist = _strip(meta.get("Artist", {}).get("value", "")) or "Unknown"
        out.append({
            "url": info.get("thumburl") or info["url"],
            "credit": f"{artist[:60]} / Wikimedia Commons ({lic})",
            "page": info.get("descriptionurl", ""),
            "pixels": info.get("width", 0) * info.get("height", 0),
            "rank": rank,
        })
    return out


def openverse(query: str) -> list[dict]:
    data = net.get_json("https://api.openverse.org/v1/images/", {
        "q": query, "license": "cc0,pdm,by,by-sa", "page_size": 20,
        "category": "photograph", "mature": "false",
    })
    out = []
    for rank, r in enumerate(data.get("results", [])):
        if min(r.get("width") or 0, r.get("height") or 0) < MIN_SIDE:
            continue
        if SKIP_WORDS.search(r.get("title") or ""):
            continue
        if (r.get("source") or "").lower() in BAD_SOURCES:
            continue
        lic = f"CC {r.get('license', '').upper()} {r.get('license_version') or ''}".strip()
        if r.get("license") in ("cc0", "pdm"):
            lic = "Public domain"
        out.append({
            "url": r["url"],
            "credit": f"{(r.get('creator') or 'Unknown')[:60]} / {r.get('source', 'Openverse')} ({lic})",
            "page": r.get("foreign_landing_url", ""),
            "pixels": (r.get("width") or 0) * (r.get("height") or 0),
            "rank": rank + 3,          # Commons usually fits news better
        })
    return out


def sharpness(path: str) -> float:
    """How sharp the sharpest parts of the photo are (higher = sharper).

    Measured on a 1080px-wide copy, in a 4x4 grid; we take a high percentile
    so a sharp subject with a soft background still passes, but an overall
    blurry/upscaled photo fails.
    """
    import cv2
    import numpy as np
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    scale = 1080 / img.shape[1]
    img = cv2.resize(img, (1080, max(1, int(img.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    h, w = img.shape
    th, tw = h // 4, w // 4
    vals = [cv2.Laplacian(img[y:y + th, x:x + tw], cv2.CV_64F).var()
            for y in range(0, 4 * th, th) for x in range(0, 4 * tw, tw)]
    return float(np.percentile(vals, 80))


def download(url: str, path: str) -> str:
    with open(path, "wb") as fh:
        fh.write(net.get(url, timeout=60, headers={"User-Agent": BOT_UA}))
    return path


def best_photo(queries: list[str], exclude: set, workdir: str) -> dict | None:
    """Return the best checked photo (with 'path' to the downloaded file), or None."""
    cands: list[dict] = []
    for q in [q for q in queries if q]:
        for finder in (wikimedia, openverse):
            try:
                for c in finder(q):
                    if c["page"] not in exclude and c["page"] not in {x["page"] for x in cands}:
                        c["query"] = q
                        cands.append(c)
            except Exception as e:
                print(f"photo search failed ({finder.__name__}, {q!r}): {str(e)[:90]}")
        if len(cands) >= MAX_DOWNLOADS:
            break

    cands.sort(key=lambda c: (c["rank"], -c["pixels"]))
    best = None
    Path(workdir).mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(cands[:MAX_DOWNLOADS]):
        path = str(Path(workdir) / f"cand{i}.jpg")
        time.sleep(1)                       # be polite to Wikimedia / Flickr
        try:
            download(c["url"], path)
            from PIL import Image
            with Image.open(path) as im:
                w, h = im.size
            if min(w, h) < MIN_SIDE:
                continue
            c["sharpness"] = round(sharpness(path), 1)
        except Exception as e:
            print(f"candidate failed: {str(e)[:90]}")
            continue
        print(f"  photo {i}: sharp={c['sharpness']:6.0f} {w}x{h} {c['page'][-60:]}")
        if c["sharpness"] < MIN_SHARPNESS:
            continue
        # earlier search results fit the story better; sharpness breaks ties
        score = c["sharpness"] / 50 - c["rank"] * 2
        if best is None or score > best["score"]:
            best = {**c, "score": score, "path": path}
    return best
