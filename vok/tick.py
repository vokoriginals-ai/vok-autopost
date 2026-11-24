"""Runs every 30 minutes (standard library only, so it's fast and cheap):

1. Read Saad's ✅/❌ taps from Telegram and mark posts approved/rejected.
2. Expire posts that are too old to be news.
3. If it's posting time, publish the oldest approved post (one per run).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta

from vok import gh, telegram
from vok.publish import PublishError, publish
from vok.state import POSTS, all_posts, config, cycle_day, in_window, load_post, load_state, now, save_post, save_state

PENDING_MAX_H = 12     # not approved within 12h → too old
APPROVED_MAX_H = 20    # approved but still not posted after 20h → too old


def apply_decisions(st: dict) -> None:
    decisions: list[tuple[str, str]] = []
    image_of: dict[str, str | None] = {}
    if telegram.enabled():
        tg, st["telegram_offset"] = telegram.fetch_decisions(st.get("telegram_offset", 0))
        decisions += tg
    issue_of: dict[str, int] = {}
    if gh.enabled():
        for decision, number, post_id, image in gh.decisions():
            decisions.append((decision, post_id))
            issue_of[post_id] = number
            image_of[post_id] = image
    for decision, post_id in decisions:
        if decision not in ("ok", "no") or not (POSTS / post_id / "post.json").exists():
            continue
        folder, meta = load_post(post_id)
        if meta.get("status") == "needs_photo":
            _photo_reply(folder, meta, post_id, decision, issue_of.get(post_id), image_of.get(post_id))
            continue
        if meta.get("status") != "pending":
            if post_id in issue_of:      # already decided/expired: just tidy up the issue
                gh.close(issue_of[post_id])
            continue
        meta["status"] = "approved" if decision == "ok" else "rejected"
        meta["decided_at"] = now().isoformat(timespec="minutes")
        save_post(folder, meta)
        print(f"{post_id}: {meta['status']}")
        if post_id in issue_of:
            gh.close(issue_of[post_id], "✅ Approved. It will post in the next free slot."
                     if decision == "ok" else "❌ Rejected.")


def _photo_reply(folder, meta, post_id, decision, number, image) -> None:
    """Owner answered a 'photo needed' post: no → reject; ok + photo → build and approve."""
    if decision == "no":
        meta["status"] = "rejected"
    elif not image:
        if not meta.get("asked_for_photo") and number:
            gh.comment(number, "Got your ok, but no photo was attached. Please reply again "
                               "from the GitHub app or website with the photo attached.")
            meta["asked_for_photo"] = True
            save_post(folder, meta)
        return
    else:
        from vok.render import render                # needs Pillow, only loaded here
        try:
            gh.download(image, str(folder / "photo.jpg"))
            render(str(folder / "photo.jpg"), meta["headline"], str(folder / "render.jpg"),
                   meta.get("label", "NEWS"))
        except Exception as e:
            print(f"{post_id}: attached photo failed: {e}")
            if number and not meta.get("photo_failed"):
                gh.comment(number, f"⚠️ Couldn't use that photo ({str(e)[:120]}). "
                                   "Please attach a JPG or PNG.")
                meta["photo_failed"] = True
                save_post(folder, meta)
            return
        credit = gh.credit_from_replies(number) if number else None
        if credit:
            meta["caption"] = meta["caption"].rstrip() + f"\n\n📸 {credit}"
            meta["photo_credit"] = credit
        meta["status"] = "approved"
    meta["decided_at"] = now().isoformat(timespec="minutes")
    save_post(folder, meta)
    print(f"{post_id}: {meta['status']} (photo request)")
    if number:
        gh.close(number, "✅ Photo added and approved. It will post in the next free slot."
                 if meta["status"] == "approved" else "❌ Skipped.")


def auto_approve(cfg: dict) -> None:
    """No reply within N minutes → approve it anyway (Saad edits after if needed)."""
    wait = cfg.get("auto_approve_after_minutes")
    if not wait:
        return
    t = now()
    for folder, meta in all_posts():
        if meta.get("status") != "pending" or not meta.get("created_at"):
            continue
        w = 10 if int(meta.get("priority", 1)) >= 3 else wait
        if (t - datetime.fromisoformat(meta["created_at"])) >= timedelta(minutes=w):
            meta["status"] = "approved"
            meta["decided_at"] = t.isoformat(timespec="minutes")
            meta["note"] = f"auto-approved: no reply in {wait} min"
            save_post(folder, meta)
            print(f"{folder.name}: auto-approved")
            if gh.enabled() and meta.get("issue"):
                gh.close(meta["issue"], f"⏱️ No reply in {wait} min, so it was approved automatically.")


def expire_old() -> None:
    t = now()
    for folder, meta in all_posts():
        status = meta.get("status")
        stamp = meta.get("decided_at") or meta.get("created_at")
        if status not in ("pending", "approved", "needs_photo") or not stamp:
            continue
        age_h = (t - datetime.fromisoformat(stamp)).total_seconds() / 3600
        if (status in ("pending", "needs_photo") and age_h > PENDING_MAX_H) or \
           (status == "approved" and age_h > APPROVED_MAX_H):
            meta["status"] = "expired"
            save_post(folder, meta)
            if gh.enabled() and meta.get("issue"):
                gh.close(meta["issue"], "⏰ Expired: no reply within 12 hours, so it was skipped.")
            print(f"{folder.name}: expired")


def publish_next(cfg: dict, st: dict) -> bool:
    t = now()
    if config().get("pause_publishing"):        # e.g. the Meta token needs renewing
        print("publishing is paused")
        return True
    if not in_window(t):
        print("outside posting hours")
        return True
    today = cycle_day(t)
    # publish times come from the posts themselves (can't be lost in a save clash)
    times = [m["published_at"] for _, m in all_posts()
             if m.get("status") == "published" and m.get("published_at")]
    if sum(1 for p in times if cycle_day(datetime.fromisoformat(p)) == today) >= cfg["posts_per_day"]:
        print("daily posting limit reached")
        return True
    breaking = any(int(m.get("priority", 1)) >= 3 for _, m in all_posts() if m.get("status") == "approved")
    if times:
        last = datetime.fromisoformat(max(times))
        gap = 10 if breaking else cfg["min_minutes_between_posts"]
        if (t - last) < timedelta(minutes=gap):
            print("too soon after the last post")
            return True

    queue = [(f, m) for f, m in all_posts()
             if m.get("status") == "approved" and (f / "render.jpg").exists()
             and (not m.get("publish_at") or datetime.fromisoformat(m["publish_at"]) <= t)]
    if not queue:
        print("nothing approved to publish")
        return True
    # breaking news first, then the oldest approval
    folder, meta = min(queue, key=lambda fm: (-int(fm[1].get("priority", 1)),
                                               fm[1].get("decided_at") or fm[1].get("created_at", "")))

    meta = json.loads((folder / "post.json").read_text(encoding="utf-8"))   # latest version
    if meta.get("status") != "approved":
        print(f"{folder.name}: no longer approved, skipping")
        return True
    if not meta.get("result"):
        try:
            from vok.publish import recent_vok_posts
            from vok.collect import _similar, _words
            mine = _words(meta["headline"])
            if any(_similar(mine, set(w)) for w in recent_vok_posts(hours=12)):
                meta["status"] = "rejected"
                meta["note"] = "VOK already posted this story"
                save_post(folder, meta)
                print(f"{folder.name}: already on VOK, skipped")
                return True
        except Exception as e:
            print(f"duplicate check failed: {str(e)[:80]}")

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
        if gh.enabled() and meta.get("issue"):
            gh.comment(meta["issue"], f"@{gh.owner()} ⚠️ Could not publish this post:\n\n{e}")
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
    if gh.enabled() and meta.get("issue"):
        gh.comment(meta["issue"], f"✅ Posted on Instagram + Facebook: {ig or ''}")
    return True


def main() -> int:
    cfg = config()
    st = load_state()
    if st.get("drip_until") and datetime.fromisoformat(st["drip_until"]) > now():
        print("the overnight publisher is running; nothing to do")
        return 0
    apply_decisions(st)
    auto_approve(cfg)
    expire_old()
    if st.get("drip_until") and datetime.fromisoformat(st["drip_until"]) > now():
        print("a drip run is publishing; this run only handles replies")
        ok = True
    else:
        ok = publish_next(cfg, st)
    save_state(st)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
