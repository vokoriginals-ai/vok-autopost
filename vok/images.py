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

# Never use photos from news agencies / stock agencies, even if a site re-shares them
AGENCY = re.compile(
    r"(reuters|associated press|\bap photo|\(ap\)|getty|afp|agence france|\bepa\b|european pressphoto|"
    r"anadolu|shutterstock|alamy|xinhua|imago|\bdpa\b|zuma|sipa|abaca|bloomberg|nurphoto|sopa images|"
    r"apa images|wenn|pa images|pa wire|press association|\bap images|ansa|kyodo|yonhap|\bwam\b|"
    r"saudi press agency|\bspa\b|\bqna\b|\bbbc\b|\bcnn\b|all rights reserved|©)", re.I)


def is_agency(*texts: str) -> bool:
    return any(t and AGENCY.search(t) for t in texts)


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


def wikimedia_person(name: str) -> list[dict]:
    """Photos that really show this person: files with their full name in the file
    name, then their Commons category. A plain text search mostly finds group photos."""
    base = {"action": "query", "format": "json", "prop": "imageinfo",
            "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 2000}
    out = _parse(_commons({**base, "generator": "search", "gsrnamespace": 6, "gsrlimit": 25,
                           "gsrsearch": f'intitle:"{name}" filetype:bitmap'}))
    sur = re.sub(r"[^a-z]", "", name.lower().split()[-1])
    out = [c for c in out if not NOT_A_PERSON.search(c["page"].rsplit("File:", 1)[-1])
           and sur in re.sub(r"[^a-z]", "", c["page"].rsplit("File:", 1)[-1].lower())]
    key = re.sub(r"[^a-z]", "", name.lower())
    for c in out:
        title = re.sub(r"[^a-z]", "", c["page"].rsplit("File:", 1)[-1].lower())
        # "Sheikh_Hasina_in_2023.jpg" shows her; "People_cheering_after_Sheikh_Hasina..." doesn't
        if not title.startswith(key):
            c["rank"] += 8
        if re.search(r"people|crowd|protest|cheering|supporters|with|and|meets|meeting",
                     c["page"].rsplit("File:", 1)[-1], re.I):
            c["rank"] += 4
    if len(out) < 3:
        time.sleep(1)
        out += _parse(_commons({**base, "generator": "categorymembers", "gcmtype": "file",
                                "gcmtitle": f"Category:{name}", "gcmlimit": 40,
                                "gcmsort": "timestamp", "gcmdir": "desc"}), newest_first=True)
    return out


def wikimedia(query: str) -> list[dict]:
    data = _commons({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 20,
        "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime", "iiurlwidth": 2000,
    })
    return _parse(data)


# ---------------- official government / state sources (free licences) ----------------
_UA = {"User-Agent": "Mozilla/5.0 (VOK news; vok.originals@gmail.com)"}
RUSSIA = re.compile(r"\b(putin|kremlin|russia|russian|moscow|lavrov|peskov|shoigu|medvedev|belousov)\b", re.I)
US_GOV = re.compile(r"\b(trump|white house|vance|rubio|hegseth|leavitt|bessent|witkoff|kushner|melania|"
                    r"washington|oval office|united states|us president)\b", re.I)
IRAN = re.compile(r"\b(iran|iranian|tehran|araghchi|pezeshkian|khamenei|baghaei|ghalibaf|larijani|"
                  r"rezaei|aref|irgc|hormuz)\b", re.I)
SPACE = re.compile(r"\b(nasa|space|rocket|launch|astronaut|orbit|moon|mars|spacex|satellite|iss)\b", re.I)


def _html(url: str) -> str:
    import urllib.request
    return urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=25) \
        .read().decode("utf-8", "replace")


def kremlin(query: str) -> list[dict]:
    """Kremlin.ru: all photos are CC BY 4.0. Newest events first."""
    from urllib.parse import quote
    h = _html("http://en.kremlin.ru/search?query=" + quote(query))
    ids = list(dict.fromkeys(re.findall(r'href="/events/president/news/(\d+)"', h)))[:3]
    out = []
    for n, eid in enumerate(ids):
        try:
            e = _html(f"http://en.kremlin.ru/events/president/news/{eid}/photos")
        except Exception:
            continue
        keys = list(dict.fromkeys(re.findall(
            r"static\.kremlin\.ru/media/events/photos/(?:small|medium|big|original)/(\w+\.jpg)", e)))
        for k, key in enumerate(keys[:6]):
            out.append({"url": f"http://static.kremlin.ru/media/events/photos/big/{key}",
                        "credit": "Kremlin.ru (CC BY 4.0)",
                        "page": f"http://en.kremlin.ru/events/president/news/{eid}/photos#{key}",
                        "pixels": 2_000_000, "rank": n * 2 + k * 0.3 - 2})
    return out


def whitehouse(query: str) -> list[dict]:
    """whitehouse.gov photo galleries: official White House photos are public domain."""
    h = _html("https://www.whitehouse.gov/gallery/")
    words = [w for w in re.findall(r"[a-z]+", query.lower()) if len(w) > 3]
    links = list(dict.fromkeys(re.findall(r'href="(https://www\.whitehouse\.gov/gallery/[^"]+/)"', h)))
    links = [l for l in links if any(w in l for w in words)] or links
    out = []
    for n, link in enumerate(links[:3]):
        try:
            g = _html(link)
        except Exception:
            continue
        imgs = list(dict.fromkeys(re.findall(
            r"(https://www\.whitehouse\.gov/wp-content/uploads/\d{4}/\d{2}/[\w\-]+?_o\.jpe?g)", g)))
        for k, u in enumerate(imgs[:6]):
            out.append({"url": u, "credit": "Official White House Photo (public domain)",
                        "page": link + "#" + u.rsplit("/", 1)[-1], "pixels": 3_000_000,
                        "rank": n * 2 + k * 0.3 - 2})
    return out


def mehr(query: str) -> list[dict]:
    """Mehr News Agency (Iran): content published under CC BY 4.0."""
    from urllib.parse import quote
    h = _html("https://en.mehrnews.com/search?q=" + quote(query))
    keys = list(dict.fromkeys(re.findall(r"media\.mehrnews\.com/d/(\d{4}/\d{2}/\d{2})/\d/(\d+)\.jpe?g", h)))
    links = list(dict.fromkeys(re.findall(r'href="(/news/\d+/[^"]+)"', h)))
    out = []
    for k, (day, num) in enumerate(keys[:8]):
        if day < "2025/01/01":
            continue
        out.append({"url": f"https://media.mehrnews.com/d/{day}/4/{num}.jpg",
                    "credit": "Mehr News Agency (CC BY 4.0)",
                    "page": "https://en.mehrnews.com" + (links[k] if k < len(links) else "") + f"#{num}",
                    "pixels": 1_500_000, "rank": k * 0.5 - 1, "min_side": 700})
    return out


def nasa(query: str) -> list[dict]:
    """NASA image library: public domain."""
    data = net.get_json("https://images-api.nasa.gov/search", {"q": query, "media_type": "image"})
    out = []
    for k, it in enumerate((data.get("collection") or {}).get("items", [])[:10]):
        d = (it.get("data") or [{}])[0]
        nid = d.get("nasa_id")
        if not nid:
            continue
        out.append({"url": f"https://images-assets.nasa.gov/image/{nid}/{nid}~orig.jpg",
                    "credit": "NASA (public domain)",
                    "page": f"https://images.nasa.gov/details/{nid}", "pixels": 4_000_000, "rank": k * 0.5})
    return out


def official_finders(query: str) -> tuple:
    """Pick the official sources that fit this story."""
    f = []
    if RUSSIA.search(query):
        f.append(kremlin)
    if US_GOV.search(query):
        f.append(whitehouse)
    if IRAN.search(query):
        f.append(mehr)
    if SPACE.search(query):
        f.append(nasa)
    return tuple(f)


def wikimedia_recent(query: str) -> list[dict]:
    """Newest uploads first: for fresh events, Commons often gets CC photos within hours
    (government and CC-licensed outlets). Only files from the last 30 days count."""
    data = _commons({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": 6, "gsrlimit": 20,
        "gsrsort": "create_timestamp_desc",
        "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime|timestamp", "iiurlwidth": 2000,
    })
    out = _parse(data, newest_first=True)
    pages = {p.get("title"): p for p in (data.get("query") or {}).get("pages", {}).values()}
    import datetime as _d
    cutoff = (_d.datetime.utcnow() - _d.timedelta(days=30)).strftime("%Y-%m-%d")
    fresh = []
    for c in out:
        from urllib.parse import unquote
        p = pages.get("File:" + unquote(c["page"].rsplit("File:", 1)[-1]).replace("_", " "))
        ts = ((p or {}).get("imageinfo") or [{}])[0].get("timestamp", "")
        if ts[:10] >= cutoff:
            c["rank"] -= 3            # a photo of the actual event beats an old general one
            fresh.append(c)
    return fresh


def pexels(query: str) -> list[dict]:
    """Pexels: free for commercial use, no agency photos. Good for objects, places, moods."""
    import os
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    data = json.loads(net.get("https://api.pexels.com/v1/search",
                              {"query": query, "per_page": 15, "orientation": "portrait"},
                              headers={"Authorization": key}))
    out = []
    for rank, r in enumerate(data.get("photos", [])):
        if min(r.get("width", 0), r.get("height", 0)) < MIN_SIDE:
            continue
        if is_agency(r.get("photographer", ""), r.get("alt", "")):
            continue
        out.append({"url": r["src"].get("large2x") or r["src"]["original"],
                    "credit": f"{r.get('photographer', 'Unknown')[:60]} / Pexels",
                    "page": r.get("url", ""), "pixels": r["width"] * r["height"], "rank": rank + 4})
    return out


def pixabay(query: str) -> list[dict]:
    """Pixabay: free for commercial use. Backup to Pexels."""
    import os
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return []
    data = net.get_json("https://pixabay.com/api/", {"key": key, "q": query[:100],
                                                     "image_type": "photo", "safesearch": "true",
                                                     "orientation": "vertical",
                                                     "per_page": 15, "min_height": 1200})
    out = []
    for rank, r in enumerate(data.get("hits", [])):
        if is_agency(r.get("user", ""), r.get("tags", "")):
            continue
        out.append({"url": r.get("largeImageURL") or r["webformatURL"],
                    "credit": f"{r.get('user', 'Unknown')[:60]} / Pixabay",
                    "page": r.get("pageURL", ""), "pixels": r.get("imageWidth", 0) * r.get("imageHeight", 0),
                    "rank": rank + 5, "min_side": 800})   # Pixabay's free size is 1280px tall
    return out


def _parse(data: dict, newest_first: bool = False) -> list[dict]:
    pages = list((data.get("query") or {}).get("pages", {}).values())
    if not newest_first:
        pages.sort(key=lambda p: p.get("index", 99))
    out = []
    for rank, p in enumerate(pages):
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = _strip(meta.get("LicenseShortName", {}).get("value", ""))
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if not OK_LICENSES.match(lic) or SKIP_WORDS.search(p.get("title", "")) or CHART.search(p.get("title", "")):
            continue
        if min(info.get("width", 0), info.get("height", 0)) < MIN_SIDE:
            continue
        artist = _strip(meta.get("Artist", {}).get("value", "")) or "Unknown"
        title = p.get("title", "")
        if is_agency(artist, _strip(meta.get("Credit", {}).get("value", "")),
                     _strip(meta.get("ImageDescription", {}).get("value", ""))[:400], title):
            continue
        # news pages use event photos; studio portraits look stiff, so they go last
        if re.search(r"official.{0,15}(portrait|photo)|headshot|portrait", title, re.I):
            rank += 6
        if re.search(r"20(2[3-9])", title):        # recent photo: a little boost
            rank -= 2
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
        if is_agency(r.get("creator") or "", r.get("title") or "", r.get("attribution") or ""):
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


CHART = re.compile(r"chart|graph|infographic|diagram|ranking|evolution|vs\b|statistics|timeline|table", re.I)
NOT_A_PERSON = re.compile(r"stadium|airport|road|street|station|bridge|building|house|hospital|"
                          r"university|college|school|statue|signature|logo|poster|mural|cartoon|"
                          r"memorial|tomb|ship|aircraft|plane|car|museum|park|square|avenue", re.I)


def _has_face(path: str) -> bool:
    """A photo OF the person: one clearly visible main face (at least 9% of the photo
    width), not a crowd or a far-away stage shot where the person is tiny."""
    try:
        from PIL import Image
        from vok.render import _faces
        im = Image.open(path)
        faces = _faces(im)
        if not faces:
            return False
        biggest = max(f[2] for f in faces)
        return biggest / im.width >= 0.09
    except Exception:
        return True          # if detection itself fails, don't block the photo


LIBRARY = Path(__file__).resolve().parent.parent / "assets" / "library"


def library_photo(person: str, queries: list[str], recent: set) -> dict | None:
    """Saad's own photos come first: match the person's name, else a tag in the queries.
    A library photo can be reused, but not one used in the last few posts."""
    try:
        lib = json.loads((LIBRARY / "library.json").read_text())
    except Exception:
        return None
    text = " ".join(q.lower() for q in queries if q)
    def ok(e):
        return min(e.get("size", [0, 0])) >= 600 and f"library:{e['file']}" not in recent
    hits = []
    def surname(n):
        return re.sub(r"[^a-z]", "", n.lower().split()[-1])[:5]   # Baghaei / Baghei both match
    words = re.sub(r"[^a-z ]", "", (person + " " + text).lower())
    if person:
        # every person in the photo must be part of the story (a photo of two leaders
        # is only used when the story is about both)
        hits = [e for e in lib if ok(e) and e.get("people")
                and surname(person) in [surname(p) for p in e["people"]]
                and all(surname(p) in words for p in e["people"])]
    if not hits:
        hits = [e for e in lib if ok(e) and not e.get("people") and any(t in text for t in e.get("tags", []))]
    if not hits:
        return None
    import random
    e = random.choice(hits)          # rotate between Saad's photos of the same person
    print(f"  photo from Saad's library: {e['file']}")
    return {"path": str(LIBRARY / e["file"]), "credit": e.get("credit", "VOK"),
            "page": f"library:{e['file']}", "sharpness": 999, "ai_generated": e.get("ai") is True,
            "ai_enhanced": e.get("ai") == "enhanced"}


def best_photo(queries: list[str], exclude: set, workdir: str, person: str = "",
               generic: bool = False) -> dict | None:
    """Return the best checked photo (with 'path' to the downloaded file), or None.
    Saad's photo library first; then photos of the person; then the event/place."""
    lib = None if generic else library_photo(person, queries, exclude)
    if lib:
        return lib
    cands: list[dict] = []
    for q in [q for q in queries if q]:
        official = official_finders(q)
        if q == person:
            finders = official + (wikimedia_person, wikimedia, openverse)
        elif generic:
            finders = (pexels, pixabay, openverse, wikimedia)
        else:
            finders = official + (wikimedia_recent, wikimedia, openverse, pexels, pixabay)
        for finder in finders:
            try:
                for c in finder(q):
                    if c["page"] not in exclude and c["page"] not in {x["page"] for x in cands}:
                        c["query"] = q
                        cands.append(c)
            except Exception as e:
                print(f"photo search failed ({finder.__name__}, {q!r}): {str(e)[:90]}")
        if len(cands) >= MAX_DOWNLOADS:
            break          # enough from the first (most fitting) queries

    order = {q: i for i, q in enumerate([q for q in queries if q])}
    for c in cands:
        c["rank"] += order.get(c["query"], 0) * 50    # person photo beats a sharper backup
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
            if min(w, h) < c.get("min_side", MIN_SIDE):
                continue
            c["sharpness"] = round(sharpness(path), 1)
        except Exception as e:
            print(f"candidate failed: {str(e)[:90]}")
            continue
        print(f"  photo {i}: sharp={c['sharpness']:6.0f} {w}x{h} {c['page'][-60:]}")
        if person and c.get("query") == person and not _has_face(path):
            print("    no face in it: not a photo of the person")
            continue
        if c["sharpness"] < MIN_SHARPNESS:
            continue
        # earlier search results fit the story better; sharpness breaks ties
        score = min(c["sharpness"], 600) / 50 - c["rank"] * 2
        if best is None or score > best["score"]:
            best = {**c, "score": score, "path": path}
    return best
