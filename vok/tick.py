"""Runs every 30 minutes (standard library only, so it's fast and cheap):

1. Read Saad's ✅/❌ taps from Telegram and mark posts approved/rejected.
2. Expire posts that are too old to be news.
3. If it's posting time, publish the oldest approved post (one per run).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

from vok import telegram
from vok.publish import PublishError, publish
from vok.state import POSTS, all_posts, config, load_post, load_state, now, save_post, save_state

PENDING_MAX_H = 12     # not approved within 12h → too old
APPROVED_MAX_H = 20    # approved but still not posted after 20h → too old


def apply_decisions(st: dict) -> None:
    if not telegram.enabled():
        return
    decisions, st["telegram_offset"] = telegram.fetch_decisions(st.get("telegram_offset", 0))
    for decision, post_id in decisions:
        if decision not in ("ok", "no") or not (POSTS / post_id / "post.json").exists():
            continue
        folder, meta = load_post(post_id)
        if meta.get("status") != "pending":
            continue
        meta["status"] = "approved" if decision == "ok" else "rejected"
        meta["decided_at"] = now().isoformat(timespec="minutes")
        save_post(folder, meta)
        print(f"{post_id}: {meta['status']}")


def expire_old() -> None:
    t = now()
    for folder, meta in all_posts():
        status = meta.get("status")
        stamp = meta.get("decided_at") or meta.get("created_at")
        if status not in ("pending", "approved") or not stamp:
            continue
        age_h = (t - datetime.fromisoformat(stamp)).total_seconds() / 3600
        if (status == "pending" and age_h > PENDING_MAX_H) or \
           (status == "approved" and age_h > APPROVED_MAX_H):
            meta["status"] = "expired"
            save_post(folder, meta)
            print(f"{folder.name}: expired")


def publish_next(cfg: dict, st: dict) -> bool:
    t = now()
    start, end = cfg["posting_hours_pkt"]
    if not (start <= t.hour < end):
        print("outside posting hours")
        return True
    today = t.date().isoformat()
    if sum(1 for p in st["published"] if p.startswith(today)) >= cfg["posts_per_day"]:
        print("daily posting limit reached")
        return True
    if st["published"]:
        last = datetime.fromisoformat(max(st["published"]))
        if (t - last) < timedelta(minutes=cfg["min_minutes_between_posts"]):
            print("too soon after the last post")
            return True

    queue = [(f, m) for f, m in all_posts()
             if m.get("status") == "approved" and (f / "render.jpg").exists()
             and (not m.get("publish_at") or datetime.fromisoformat(m["publish_at"]) <= t)]
    if not queue:
        print("nothing approved to publish")
        return True
    folder, meta = min(queue, key=lambda fm: fm[1].get("decided_at") or fm[1].get("created_at", ""))

    def save_progress(res: dict) -> None:
        meta["result"] = res
        save_post(folder, meta)

    try:
        result = publish(str(folder / "render.jpg"), meta["caption"],
                         tuple(meta.get("targets", ["facebook", "instagram"])),
                         done=meta.get("result"), on_step=save_progress)
    except PublishError as e:
        meta["status"] = "failed"
        meta["error"] = str(e)
        save_post(folder, meta)
        if telegram.enabled():
            telegram.send_text(f"⚠️ Could not publish:\n{meta['headline']}\n\n{e}")
        print(f"{folder.name}: FAILED – {e}")
        return False

    meta["status"] = "published"
    meta["published_at"] = t.isoformat(timespec="minutes")
    meta["result"] = result
    meta.pop("error", None)
    save_post(folder, meta)
    st["published"].append(t.isoformat(timespec="minutes"))
    ig = (result.get("instagram") or {}).get("permalink")
    print(f"{folder.name}: published {ig}")
    if telegram.enabled():
        telegram.send_text(f"✅ Posted: {meta['headline']}\n{ig or ''}")
    return True


def main() -> int:
    cfg = config()
    st = load_state()
    apply_decisions(st)
    expire_old()
    ok = publish_next(cfg, st)
    save_state(st)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
