"""Publish posts from the queue in posts/.

Each post lives in its own folder:

    posts/<post-id>/
        post.json    – headline, caption, label, status, publish time
        photo.jpg    – the source photo
        render.jpg   – the finished VOK design (created automatically)

post.json "status" moves:  draft → approved → published  (or failed)

Commands:
    python -m vok.run render  <post-id>   # just make render.jpg (preview)
    python -m vok.run publish <post-id>   # render + publish this post now
    python -m vok.run due                 # publish every approved post whose time has come
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vok.publish import PublishError, publish
from vok.render import render

ROOT = Path(__file__).resolve().parent.parent
POSTS = ROOT / "posts"
PKT = timezone(timedelta(hours=5))


def _load(post_id: str) -> tuple[Path, dict]:
    folder = POSTS / post_id
    meta_path = folder / "post.json"
    if not meta_path.exists():
        sys.exit(f"No post found: {meta_path}")
    return folder, json.loads(meta_path.read_text(encoding="utf-8"))


def _save(folder: Path, meta: dict) -> None:
    (folder / "post.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def do_render(post_id: str) -> Path:
    folder, meta = _load(post_id)
    photo = next(folder.glob("photo.*"), None)
    if photo is None:
        sys.exit(f"{post_id}: no photo.* file in {folder}")
    out = folder / "render.jpg"
    focus = tuple(meta["focus"]) if meta.get("focus") else None
    render(str(photo), meta["headline"], str(out), meta.get("label", "NEWS"), focus)
    print(f"rendered {out}")
    return out


def do_publish(post_id: str) -> bool:
    folder, meta = _load(post_id)
    if meta.get("status") == "published":
        print(f"{post_id}: already published, skipping")
        return True
    image = do_render(post_id)

    def save_progress(res: dict) -> None:
        meta["result"] = res
        _save(folder, meta)

    try:
        result = publish(str(image), meta["caption"],
                         tuple(meta.get("targets", ["facebook", "instagram"])),
                         done=meta.get("result"), on_step=save_progress)
    except PublishError as e:
        meta["status"] = "failed"
        meta["error"] = str(e)
        _save(folder, meta)
        print(f"{post_id}: FAILED – {e}")
        return False
    meta["status"] = "published"
    meta["published_at"] = datetime.now(PKT).isoformat(timespec="minutes")
    meta["result"] = result
    meta.pop("error", None)
    _save(folder, meta)
    for platform, info in result.items():
        print(f"{post_id}: published on {platform} → {info.get('permalink')}")
    return True


def do_due() -> bool:
    now = datetime.now(PKT)
    ok = True
    for meta_path in sorted(POSTS.glob("*/post.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("status") != "approved":
            continue
        when = meta.get("publish_at")
        if when and datetime.fromisoformat(when) > now:
            continue
        ok &= do_publish(meta_path.parent.name)
    return ok


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "render":
        do_render(sys.argv[2])
    elif cmd == "publish":
        sys.exit(0 if do_publish(sys.argv[2]) else 1)
    elif cmd == "due":
        sys.exit(0 if do_due() else 1)
    else:
        sys.exit(__doc__)
