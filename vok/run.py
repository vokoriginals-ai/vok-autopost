"""Manual commands (the automatic jobs are make_posts.py and tick.py).

    python -m vok.run render  <post-id>   # (re)make render.jpg
    python -m vok.run publish <post-id>   # publish this post right now
    python -m vok.run publish-all [gap]   # publish all approved posts now, gap seconds apart
"""

from __future__ import annotations

import sys

from vok.publish import PublishError, publish
from vok.state import load_post, now, save_post


def do_render(post_id: str):
    from vok.render import render          # needs Pillow; only imported when used
    folder, meta = load_post(post_id)
    photo = next(folder.glob("photo.*"))
    out = folder / "render.jpg"
    focus = tuple(meta["focus"]) if meta.get("focus") else None
    render(str(photo), meta["headline"], str(out), meta.get("label", "NEWS"), focus)
    print(f"rendered {out}")
    return out


def do_publish(post_id: str) -> bool:
    folder, meta = load_post(post_id)
    if meta.get("status") == "published":
        print(f"{post_id}: already published")
        return True
    image = folder / "render.jpg"
    if not image.exists():
        image = do_render(post_id)

    def save_progress(res: dict) -> None:
        meta["result"] = res
        save_post(folder, meta)

    try:
        result = publish(str(image), meta["caption"],
                         tuple(meta.get("targets", ["facebook", "instagram"])),
                         done=meta.get("result"), on_step=save_progress)
    except PublishError as e:
        meta["status"], meta["error"] = "failed", str(e)
        save_post(folder, meta)
        print(f"{post_id}: FAILED – {e}")
        return False
    meta["status"] = "published"
    meta["published_at"] = now().isoformat(timespec="minutes")
    meta["result"] = result
    meta.pop("error", None)
    save_post(folder, meta)
    for platform, info in result.items():
        print(f"{post_id}: on {platform} → {info.get('permalink')}")
    return True


def publish_all_approved(gap_seconds: int = 180) -> bool:
    """Publish every approved post now, oldest first, with a pause between them."""
    import time
    from vok.state import all_posts, load_state, save_state
    queue = sorted((m.get("decided_at") or m.get("created_at", ""), f.name)
                   for f, m in all_posts() if m.get("status") == "approved")
    st = load_state()
    ok = True
    for i, (_, post_id) in enumerate(queue):
        if i:
            time.sleep(gap_seconds)
        good = do_publish(post_id)
        ok &= good
        if good:
            st.setdefault("published", []).append(now().isoformat(timespec="minutes"))
    save_state(st)
    return ok


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "publish-all":
        gap = int(sys.argv[2]) if len(sys.argv) > 2 else 180
        sys.exit(0 if publish_all_approved(gap) else 1)
    if len(sys.argv) < 3 or sys.argv[1] not in ("render", "publish"):
        sys.exit(__doc__)
    if sys.argv[1] == "render":
        do_render(sys.argv[2])
    else:
        sys.exit(0 if do_publish(sys.argv[2]) else 1)
