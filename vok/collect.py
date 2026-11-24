"""Find today's biggest Middle East / world stories.

Reads the RSS feeds in config.json, groups headlines about the same event,
and ranks the groups by how many different outlets cover them, how fresh
they are, and whether they involve conflict or controversy.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from vok import net

STOP = set("""a an the and or but of in on at to for from by with about after before over
under into as is are was were be been being has have had will would can could may might
says said say new news report reports latest live update updates video watch amid against
not no its it this that these those his her their our your than then also more most first
how why what who when where which while during up down out off near ahead just still
year years day days week weeks us uk""".split())

HOT = set("""attack attacks strike strikes struck killed kills dead death deaths bomb bombing
missile missiles drone drones war ceasefire truce protest protests clash clashes riot arrest
arrested ban banned sanction sanctions threat threatens warns warning accuse accuses slams
scandal leaked leak outrage viral crisis seized seize hostage hostages invasion explosion
blast fire collapse resign resigns ousted coup execution executed nuclear blockade""".split())

TAG_RE = re.compile(r"<[^>]+>")

ALIASES = {"BBC News": "BBC", "Al Arabiya English": "Al Arabiya",
           "The Times of Israel": "Times of Israel", "Bloomberg.com": "Bloomberg",
           "Euronews.com": "Euronews", "Anadolu Ajansı": "Anadolu"}


def _clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", s or ""))).strip()


def _words(title: str) -> set[str]:
    toks = re.findall(r"[a-z0-9']+", title.lower())
    return {t.strip("'") for t in toks if len(t) > 2 and t not in STOP}


def fetch(feeds: list[dict], max_age_hours: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    items: list[dict] = []
    for f in feeds:
        if f.get("instagram"):
            items += _instagram(f, now, max_age_hours)
            continue
        try:
            root = ET.fromstring(net.get(f["url"], timeout=25))
        except Exception as e:  # one bad feed shouldn't stop the run
            print(f"feed failed: {f['name']} {f['url'][:60]} – {e}")
            continue
        for it in root.iter("item"):
            title = _clean(it.findtext("title"))
            if not title:
                continue
            source = f["name"]
            src_el = it.find("source")
            if src_el is not None and src_el.text:      # Google News: real publisher
                source = _clean(src_el.text)
                title = re.sub(rf"\s+-\s+{re.escape(source)}$", "", title)
            source = ALIASES.get(source, source)
            try:
                pub = parsedate_to_datetime(it.findtext("pubDate") or "")
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
            except Exception:
                pub = now
            if now - pub > timedelta(hours=max_age_hours):
                continue
            items.append({
                "title": title,
                "summary": _clean(it.findtext("description"))[:500],
                "link": (it.findtext("link") or "").strip(),
                "source": source,
                "published": pub.isoformat(),
                "words": _words(title),
            })
    print(f"fetched {len(items)} fresh headlines")
    return items


def _instagram(f: dict, now, max_age_hours: int) -> list[dict]:
    """Latest posts of a public Instagram business page (e.g. @gethefame.official),
    read through VOK's own Instagram connection. These are tips: a story still needs
    a trusted outlet reporting it before VOK posts it."""
    import os
    from vok.publish import GRAPH, IG_ID
    if not os.environ.get("META_PAGE_TOKEN"):
        return []
    fields = (f"business_discovery.username({f['instagram']})"
              "{media.limit(%d){caption,timestamp,permalink}}" % f.get("limit", 25))
    try:
        data = net.get_json(f"{GRAPH}/{IG_ID}", {"fields": fields,
                                                  "access_token": os.environ["META_PAGE_TOKEN"]})
    except Exception as e:
        print(f"instagram source failed: {f['instagram']} {str(e)[:120]}")
        return []
    out = []
    for m in (data.get("business_discovery", {}).get("media", {}) or {}).get("data", []):
        cap = (m.get("caption") or "").strip()
        if not cap:
            continue
        try:
            pub = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        except Exception:
            pub = now
        if now - pub > timedelta(hours=max_age_hours):
            continue
        title = _clean(cap.splitlines()[0])[:200]
        out.append({"title": title, "summary": _clean(cap)[:500], "link": m.get("permalink", ""),
                    "source": f["name"], "published": pub.isoformat(), "words": _words(title)})
    print(f"instagram {f['instagram']}: {len(out)} fresh posts")
    return out


def _similar(a: set[str], b: set[str]) -> bool:
    common = len(a & b)
    return common >= 3 or (common >= 2 and common / max(1, min(len(a), len(b))) >= 0.5)


def cluster(items: list[dict]) -> list[dict]:
    groups: list[dict] = []
    for it in sorted(items, key=lambda x: x["published"], reverse=True):
        for g in groups:
            if _similar(it["words"], g["words"]):
                g["items"].append(it)
                g["words"] |= it["words"]
                break
        else:
            groups.append({"items": [it], "words": set(it["words"])})

    now = datetime.now(timezone.utc)
    for g in groups:
        g["sources"] = sorted({i["source"] for i in g["items"]})
        newest = max(datetime.fromisoformat(i["published"]) for i in g["items"])
        age_h = (now - newest).total_seconds() / 3600
        hot = len(g["words"] & HOT)
        g["score"] = 3 * len(g["sources"]) + max(0, 6 - age_h / 2) + 2 * min(hot, 3)
        g["headline"] = g["items"][0]["title"]
    groups.sort(key=lambda g: g["score"], reverse=True)
    return groups


def overlaps(words: set[str], seen: list[list[str]]) -> bool:
    return any(_similar(words, set(s)) for s in seen)


# clear sports words block a story on their own; ambiguous ones ("final", "league", "cup")
# only count when two or more appear together
SPORTS_STRONG = re.compile(r"\b(football|soccer|cricket|tennis|golf|nba|nfl|mlb|nhl|ufc|formula 1|f1|"
                           r"grand prix|olympics?|world cup|premier league|la liga|bundesliga|serie a|"
                           r"champions league|atp|wta|wimbledon|grand slam|striker|goalkeeper|"
                           r"pitcher|quarterback|touchdown|innings|wicket|t20|odi|ipl|psl|boxing|"
                           r"fifa|uefa|icc|matchday|hat trick|ballon d.or|mets|yankees|lakers|afcon|copa america|court of arbitration for sport|footballer|cricketer|athlete|athletics|super bowl|world series|ligue 1|messi|ronaldo|neymar|mbappe|babar azam|virat kohli)\b", re.I)
SPORTS_WEAK = re.compile(r"\b(match|matches|final|finals|semifinal|league|cup|tournament|coach|"
                         r"medal|title|season|club|player|players|team|transfer|stadium|fans)\b", re.I)


def is_sports(text: str) -> bool:
    return bool(SPORTS_STRONG.search(text)) or len(set(m.lower() for m in SPORTS_WEAK.findall(text))) >= 2


def top_stories(cfg: dict, seen: list[list[str]], limit: int) -> list[dict]:
    groups = cluster(fetch(cfg["feeds"], cfg["story_max_age_hours"]))
    picked = []
    for g in groups:
        if len(g["sources"]) < cfg["min_sources"]:
            continue
        trusted = set(cfg.get("trusted_sources", []))
        if cfg.get("require_trusted_source") and not trusted & set(g["sources"]):
            continue                      # at least one credible outlet must carry it
        g["trusted"] = sorted(trusted & set(g["sources"]))
        g["score"] += 2 * len(g["trusted"])
        if overlaps(g["words"], seen):
            continue
        if any(is_sports(it["title"]) for it in g["items"][:3]):
            print(f"skip sports: {g['items'][0]['title'][:70]}")
            continue
        picked.append(g)
        if len(picked) >= limit:
            break
    return picked


if __name__ == "__main__":
    import json
    cfg = json.load(open("config.json", encoding="utf-8"))
    for g in top_stories(cfg, [], 10):
        print(f"{g['score']:5.1f}  {len(g['sources'])} src  {g['headline']}")
        print("        ", ", ".join(g["sources"]))
