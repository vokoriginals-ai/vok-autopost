"""Manual commands (the automatic jobs are make_posts.py and tick.py).

    python -m vok.run render  <post-id>   # (re)make render.jpg
    python -m vok.run publish <post-id>   # publish this post right now
    python -m vok.run publish-all [gap]   # publish all approved posts now, gap seconds apart
    python -m vok.run drip                # stay on: approvals + spread posts until 10 am
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


def drip(max_hours: float = 5.5) -> None:
    """Keep running: every 5 min read replies, auto-approve, and publish the next post
    when it is due. Posts are spread evenly so the queue lasts until the window ends
    (gap 30 to 60 min). After ~5.5 h it starts a fresh copy of itself (GitHub limit 6 h)."""
    import json, os, time, urllib.request
    from datetime import datetime, timedelta
    from vok import tick
    from vok.state import all_posts, config, in_window, load_state, save_state
    started = time.time()
    st0 = load_state()
    st0["drip_until"] = (now() + timedelta(hours=max_hours, minutes=10)).isoformat()
    save_state(st0)
    while time.time() - started < max_hours * 3600:
        cfg = config()
        t = now()
        if in_window(t):
            queue = sum(1 for _, m in all_posts() if m.get("status") in ("approved", "pending"))
            end = t.replace(hour=cfg["posting_hours_pkt"][1], minute=0, second=0, microsecond=0)
            if end <= t:
                end += timedelta(days=1)
            left_min = (end - t).total_seconds() / 60
            gap = max(30, min(60, int(left_min / max(queue, 1))))
            cfg["min_minutes_between_posts"] = gap
            st = load_state()
            st["drip_until"] = st0["drip_until"]
            tick.apply_decisions(st)
            tick.auto_approve(cfg)
            tick.expire_old()
            tick.publish_next(cfg, st)
            save_state(st)
            os.system('git add posts data >/dev/null 2>&1 && git commit -qm "drip: update posts [skip ci]" '
                      '&& (git pull -q --rebase -X theirs || git rebase --abort) && git push -q')
        elif not any(m.get("status") in ("approved", "pending") for _, m in all_posts()):
            print("outside window and nothing queued: stopping")
            return
        time.sleep(300)
    # hand over to a fresh run so the queue keeps going
    if any(m.get("status") in ("approved", "pending") for _, m in all_posts()):
        repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
        if repo and token:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{repo}/actions/workflows/tick.yml/dispatches",
                data=json.dumps({"ref": "main", "inputs": {"drip": "yes"}}).encode(), method="POST",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                         "User-Agent": "vok-autopost"})
            urllib.request.urlopen(req, timeout=30)
            print("handed over to a new drip run")


if __name__ == "__main__":
    if sys.argv[1:2] == ["drip"]:
        drip()
        sys.exit(0)
    if len(sys.argv) >= 2 and sys.argv[1] == "publish-all":
        gap = int(sys.argv[2]) if len(sys.argv) > 2 else 180
        sys.exit(0 if publish_all_approved(gap) else 1)
    if len(sys.argv) < 3 or sys.argv[1] not in ("render", "publish"):
        sys.exit(__doc__)
    if sys.argv[1] == "render":
        do_render(sys.argv[2])
    else:
        sys.exit(0 if do_publish(sys.argv[2]) else 1)
