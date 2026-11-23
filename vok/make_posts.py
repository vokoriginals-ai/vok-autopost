"""Make new posts: find stories → write with Gemini → find photo → design →
send to Telegram for approval. Runs a few times a day from GitHub.
"""

from __future__ import annotations

import sys
from datetime import timedelta

import shutil

from vok import collect, gh, images, telegram
from vok.words import add_ai_note, clean
from vok.render import render
from vok.state import (all_posts, config, load_state, now, save_post, save_state, slug,
                       POSTS)
from vok.write import WriteError, write_post


def main(count: int | None = None, auto_approve: bool = False, hold: bool = False) -> int:
    cfg = config()
    st = load_state()
    from vok.state import cycle_day
    from datetime import datetime as _dt
    today = cycle_day()

    made_today = sum(1 for _, m in all_posts()
                     if m.get("created_at") and cycle_day(_dt.fromisoformat(m["created_at"])) == today
                     and m.get("status") not in ("rejected", "expired"))
    room = min(count or cfg["posts_per_run"], cfg["posts_per_day"] - made_today)
    if room <= 0:
        print(f"daily limit reached ({made_today} made today)")
        return 0

    recent = (now() - timedelta(days=2)).isoformat()
    seen = [s["words"] for s in st["seen"] if s.get("at", "") >= recent]
    # stories VOK already posted (by anyone on the team) count as seen
    try:
        from vok.publish import recent_vok_posts
        seen += recent_vok_posts()
    except Exception as e:
        print(f"couldn't read VOK's recent posts: {str(e)[:100]}")
    stories = collect.top_stories(cfg, seen, limit=room * 3)
    print(f"{len(stories)} candidate stories, room for {room}")

    if gh.enabled():
        gh.ensure_label()
    made = 0
    asked = 0          # photo requests sent this run (max 2, so emails stay few)
    for story in stories:
        if made >= room:
            break
        st["seen"].append({"at": now().isoformat(), "words": sorted(story["words"]),
                           "headline": story["headline"]})
        try:
            w = write_post(story, cfg["gemini_models"])
        except Exception as e:
            if not isinstance(e, WriteError):
                print(f"writer crashed on this story, skipping: {str(e)[:100]}")
                continue
            print(f"writer error: {e}")
            if "rejected" in str(e):
                break                     # bad key: no point continuing
            import time
            time.sleep(60)                # Gemini busy: pause, then try the next story
            continue
        if not w.get("publishable"):
            print(f"skip: {story['headline'][:70]} – {w.get('reason')}")
            continue

        used = {u["page"] for u in st.setdefault("photos", [])}
        post_id = f"{now():%Y%m%d-%H%M}-{slug(w['headline'])}"
        folder = POSTS / post_id
        photo = images.best_photo([w.get("photo_person", ""), w.get("image_query", ""),
                                   w.get("image_query_backup", "")],
                                  person=w.get("photo_person", ""),
                                  exclude=used, workdir=str(folder / "_candidates"))
        if not photo:
            shutil.rmtree(folder / "_candidates", ignore_errors=True)
            if auto_approve or hold or not gh.enabled() or asked >= 2:
                print(f"skip (no sharp free photo): {w['headline']}")
                shutil.rmtree(folder, ignore_errors=True)
                continue
            meta = {
                "headline": clean(w["headline"]), "label": w["label"],
                "caption": clean(w["caption"].rstrip()), "status": "needs_photo",
                "ai_image": False, "created_at": now().isoformat(timespec="minutes"),
                "targets": ["facebook", "instagram"],
                "photo_hint": ", ".join(x for x in (w.get("photo_person"), w.get("image_query")) if x),
                "sources_named": story["sources"],
                "source_links": [i["link"] for i in story["items"][:8]],
            }
            folder.mkdir(parents=True, exist_ok=True)
            meta["issue"] = gh.create_photo_request_issue(post_id, meta)
            save_post(folder, meta)
            print(f"photo needed: {post_id}")
            asked += 1
            made += 1
            continue

        headline = clean(w["headline"])
        try:
            shutil.copy(photo["path"], folder / "photo.jpg")
            render(str(folder / "photo.jpg"), headline, str(folder / "render.jpg"), w["label"])
        except Exception as e:
            print(f"skip (render failed): {e}")
            shutil.rmtree(folder, ignore_errors=True)
            continue
        finally:
            shutil.rmtree(folder / "_candidates", ignore_errors=True)

        caption = clean(w["caption"].rstrip())
        if photo.get("ai_generated"):
            caption = add_ai_note(caption)
        caption += f"\n\n📸 {photo['credit']}"
        meta = {
            "headline": headline,
            "label": w["label"],
            "caption": caption,
            "status": "hold" if hold else ("approved" if auto_approve else "pending"),
            "priority": int(w.get("priority") or 1),
            "ai_image": bool(photo.get("ai_generated")),
            "created_at": now().isoformat(timespec="minutes"),
            "targets": ["facebook", "instagram"],
            "photo_credit": photo["credit"],
            "photo_page": photo["page"],
            "photo_sharpness": photo["sharpness"],
            "sources_named": story["sources"],
            "source_links": [i["link"] for i in story["items"][:8]],
        }
        if hold:
            meta["note"] = "held for review (no email); set status to approved to release"
        elif auto_approve:
            meta["decided_at"] = now().isoformat(timespec="minutes")
            meta["note"] = "auto-approved batch (no email)"
        elif gh.enabled():
            import os
            from vok.publish import host_image
            preview = host_image(str(folder / "render.jpg")) if os.environ.get("META_PAGE_TOKEN") else None
            meta["issue"] = gh.create_post_issue(post_id, meta, preview)
        save_post(folder, meta)
        st["photos"].append({"at": now().isoformat(), "page": photo["page"]})
        if telegram.enabled() and not (auto_approve or hold):
            telegram.send_for_approval(post_id, str(folder / "render.jpg"), meta)
        print(f"made {post_id}")
        made += 1

    save_state(st)
    print(f"done: {made} new posts")
    return 0


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=None, help="how many posts to make this run")
    ap.add_argument("--approve", action="store_true", help="approve them immediately (no email)")
    ap.add_argument("--hold", action="store_true", help="park them for review (no email, not posted)")
    a = ap.parse_args()
    sys.exit(main(a.count, a.approve, a.hold))
