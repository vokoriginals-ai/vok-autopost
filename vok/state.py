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


def save_post(folder: Path, meta: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "post.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def all_posts() -> list[tuple[Path, dict]]:
    out = []
    for p in sorted(POSTS.glob("*/post.json")):
        out.append((p.parent, json.loads(p.read_text(encoding="utf-8"))))
    return out


def slug(text: str, n: int = 5) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words[:n]) or "post"
