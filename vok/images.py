"""Find a free-to-use photo for a story.

1. Wikimedia Commons: real news photos of leaders, cities, events.
2. Openverse: backup search across Creative Commons photo sites.

Only public-domain / CC0 / CC BY / CC BY-SA images are used, and the
credit line is returned so it can go in the caption (required by CC BY).
"""

from __future__ import annotations

import html
import re

from vok import net

OK_LICENSES = re.compile(r"^(cc0|public domain|pd|cc by(-sa)?( \d\.\d)?)", re.I)
TAG_RE = re.compile(r"<[^>]+>")
SKIP_WORDS = re.compile(
    r"(logo|flag|map|coat of arms|seal|icon|diagram|chart|svg|signature|painting|engraving"
    r"|circa|(?<![a-z0-9])c\. ?\d|(?<!\d)1[5-9]\d\d(?!\d))", re.I)   # no archive/historic images for news


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub("", s or ""))).strip()


BOT_UA = "VokAutopost/1.0 (https://github.com/vokoriginals-ai/vok-autopost) news-photo-search"


def _commons(params: dict) -> dict:
    import json
    import time
    for attempt in range(3):
        try:
            return json.loads(net.get("https://commons.wikimedia.org/w/api.php", params,
                                      headers={"User-Agent": BOT_UA}))
        except net.HTTPError as e:
            if e.status != 429 or attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    return {}


def wikimedia(query: str, exclude: set = frozenset()) -> dict | None:
    data = _commons({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 15,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 1600,
    })
    pages = sorted((data.get("query") or {}).get("pages", {}).values(),
                   key=lambda p: p.get("index", 99))
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = _strip(meta.get("LicenseShortName", {}).get("value", ""))
        title = p.get("title", "")
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if not OK_LICENSES.match(lic) or SKIP_WORDS.search(title):
            continue
        if min(info.get("width", 0), info.get("height", 0)) < 700:
            continue
        if info.get("descriptionurl") in exclude:
            continue
        artist = _strip(meta.get("Artist", {}).get("value", "")) or "Unknown"
        return {
            "url": info.get("thumburl") or info["url"],
            "credit": f"{artist[:60]} / Wikimedia Commons ({lic})",
            "page": info.get("descriptionurl", ""),
        }
    return None


def openverse(query: str, exclude: set = frozenset()) -> dict | None:
    data = net.get_json("https://api.openverse.org/v1/images/", {
        "q": query, "license": "cc0,pdm,by,by-sa", "page_size": 20,
        "category": "photograph", "mature": "false",
    })
    for r in data.get("results", []):
        if min(r.get("width") or 0, r.get("height") or 0) < 700:
            continue
        if SKIP_WORDS.search(r.get("title") or "") or r.get("foreign_landing_url") in exclude:
            continue
        lic = f"CC {r.get('license', '').upper()} {r.get('license_version') or ''}".strip()
        if r.get("license") in ("cc0", "pdm"):
            lic = "Public domain"
        return {
            "url": r["url"],
            "credit": f"{(r.get('creator') or 'Unknown')[:60]} / {r.get('source', 'Openverse')} ({lic})",
            "page": r.get("foreign_landing_url", ""),
        }
    return None


def find_photo(*queries: str, exclude: set = frozenset()) -> dict | None:
    for q in [q for q in queries if q]:
        for finder in (wikimedia, openverse):
            try:
                hit = finder(q, exclude)
            except Exception as e:
                print(f"photo search failed ({finder.__name__}, {q!r}): {e}")
                continue
            if hit:
                hit["query"] = q
                return hit
    return None


def download(url: str, path: str) -> str:
    with open(path, "wb") as fh:
        fh.write(net.get(url, timeout=60, headers={"User-Agent": BOT_UA}))
    return path


if __name__ == "__main__":
    import sys
    print(find_photo(*sys.argv[1:]))
