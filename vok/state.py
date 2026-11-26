"""Small shared helpers: config, saved state, post folders, Pakistan time."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSTS = ROOT / "posts"
STATE = ROOT / "data" / "state.json"
PKT = timezone(timedelta(hours=5))


def now() -> datetime:
    return datetime.now(PKT)


def config() -> dict:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"telegram_offset": 0, "seen": [], "published": []}


def save_state(st: dict) -> None:
    STATE.parent.mkdir(exist_ok=True)
    # keep only the last 4 days of history so the file stays small
    cutoff = (now() - timedelta(days=4)).isoformat()
    st["seen"] = [s for s in st.get("seen", []) if s.get("at", "") >= cutoff]
    st["published"] = [p for p in st.get("published", []) if p >= cutoff]
    photo_cutoff = (now() - timedelta(days=30)).isoformat()   # never reuse a photo within 30 days
    st["photos"] = [p for p in st.get("photos", []) if p.get("at", "") >= photo_cutoff]
    STATE.write_text(json.dumps(st, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def load_post(post_id: str) -> tuple[Path, dict]:
    folder = POSTS / post_id
    return folder, json.loads((folder / "post.json").read_text(encoding="utf-8"))


def _clean_text(text: str) -> str:
    """Join broken emoji halves (surrogates) from the AI's text, drop any left over."""
    try:
        return text.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeError:
        return text.encode("utf-8", "replace").decode("utf-8")


def save_post(folder: Path, meta: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    data = _clean_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    tmp = folder / "post.json.tmp"
    tmp.write_text(data, encoding="utf-8")          # never leave a half-written post.json
    tmp.replace(folder / "post.json")


def all_posts() -> list[tuple[Path, dict]]:
    out = []
    for p in sorted(POSTS.glob("*/post.json")):
        try:
            out.append((p.parent, json.loads(p.read_text(encoding="utf-8"))))
        except Exception as e:                  # one broken file must not stop everything
            print(f"skipping broken {p.parent.name}: {str(e)[:60]}")
    return out


def slug(text: str, n: int = 5) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words[:n]) or "post"


def cycle_day(t=None) -> str:
    """The posting 'day' starts at 12 pm PKT and runs to the next morning."""
    from datetime import timedelta as _td
    t = t or now()
    return (t - _td(hours=config().get("cycle_start_hour_pkt", 12))).date().isoformat()


def in_window(t=None) -> bool:
    """True inside posting hours; [12, 10] means 12 pm until 10 am next day."""
    t = t or now()
    start, end = config()["posting_hours_pkt"]
    return start <= t.hour < end if start < end else (t.hour >= start or t.hour < end)
