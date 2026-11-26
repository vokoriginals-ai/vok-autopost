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


def _save_to_github(post_id: str) -> None:
    """Commit each post as soon as it exists, so a stopped run loses nothing."""
    import os
    if os.environ.get("GITHUB_ACTIONS"):
        os.system('git config user.name vok-bot; git config user.email vok-bot@users.noreply.github.com; '
                  f'git add posts data && git commit -qm "New post {post_id} [skip ci]" '
                  '&& (git pull -q --rebase -X theirs || git rebase --abort) && git push -q')


def main(count: int | None = None, auto_approve: bool = False, hold: bool = False) -> int:
    cfg = config()
    st = load_state()
    from vok.state import cycle_day
    from datetime import datetime as _dt
    today = cycle_day()

    made_today = sum(1 for _, m in all_posts()
                     if m.get("created_at") and cycle_day(_dt.fromisoformat(m["created_at"])) == today
                     and m.get("status") not in ("rejected", "expired", "needs_photo", "failed"))
    room = min(count or cfg["posts_per_run"], cfg["posts_per_day"] - made_today)
    breaking_only = False
    if room <= 0:
        # the daily target is reached, but BREAKING news must still go out
        print(f"daily limit reached ({made_today} made today): breaking news only")
        breaking_only, room = True, 2

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
    import time as _time
    run_started = _time.time()
    made = 0
    asked = 0          # photo requests sent this run (max 2, so emails stay few)
    for story in stories:
        if made >= room:
            break
        if _time.time() - run_started > 40 * 60:      # job limit is 55 min: stop cleanly
            print("time budget used up; the next run continues")
            break
        def mark_seen():
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
            time.sleep(20)                # Gemini busy: short pause, then the next story
            continue
        mark_seen()
        if not w.get("publishable"):
            print(f"skip: {story['headline'][:70]} – {w.get('reason')}")
            continue
        if breaking_only and int(w.get("priority") or 1) < 3:
            print(f"skip (daily limit, not breaking): {w['headline'][:70]}")
            continue

        week_ago = (now() - timedelta(days=7)).isoformat()
        # web photos: never twice. Saad's library photos: not again within 7 days
        used = {u["page"] for u in st.setdefault("photos", [])
                if not u["page"].startswith("library:") or u.get("at", "") >= week_ago}
        post_id = f"{now():%Y%m%d-%H%M}-{slug(w['headline'])}"
        n = 2
        while (POSTS / post_id).exists():          # never overwrite another post
            post_id = f"{now():%Y%m%d-%H%M}-{slug(w['headline'])}-{n}"
            n += 1
        folder = POSTS / post_id
        headline = clean(w["headline"])
        highlight = clean(w.get("highlight") or "")
        # Photo search in rounds: 1) the person / the event itself, 2) safe generic pictures
        # (Pexels, Pixabay, Openverse). Every pick must pass the Gemini photo check.
        rounds = [([w.get("photo_person", ""), w.get("image_query", ""),
                    w.get("image_query_backup", "")], False),
                  ([q for q in (w.get("photo_ideas") or [])[:3] if isinstance(q, str)], True)]
        photo, why = None, "no safe photo found"
        folder.mkdir(parents=True, exist_ok=True)
        for queries, generic in rounds:
            if not any(queries):
                continue
            cand = images.best_photo(queries, person="" if generic else w.get("photo_person", ""),
                                     exclude=used, workdir=str(folder / "_candidates"), generic=generic)
            if not cand:
                continue
            try:
                shutil.copy(cand["path"], folder / "photo.jpg")
                render(str(folder / "photo.jpg"), headline, str(folder / "render.jpg"), w["label"],
                       highlight=highlight)
            except Exception as e:
                print(f"render failed: {e}")
                continue
            from vok.render import face_visible
            if not generic and w.get("photo_person") and not cand["page"].startswith("library:") \
                    and not face_visible(str(folder / "render.jpg")):
                print("  photo REJECTED: the person's face is not fully visible in the post")
                used.add(cand["page"])
                continue
            from vok.write import check_photo
            ok, why = check_photo(str(folder / "render.jpg"), headline, w["caption"][:600], cfg["gemini_models"])
            print(f"  photo check ({'generic' if generic else 'main'}): {'OK' if ok else 'REJECTED'} ({why})")
            if ok:
                photo = cand
                break
            used.add(cand["page"])
            (folder / "render.jpg").unlink(missing_ok=True)
            (folder / "photo.jpg").unlink(missing_ok=True)
        shutil.rmtree(folder / "_candidates", ignore_errors=True)

        if not photo and w["label"] == "BREAKING":
            # hard news never waits for a photo: clean VOK headline card instead
            from vok.render import render_text_card
            render_text_card(headline, str(folder / "render.jpg"), w["label"], highlight)
            photo = {"credit": "", "page": "text-card", "sharpness": 0, "text_card": True}
            print(f"  no usable photo ({why}): headline card used")

        if not photo:
            # Saad: no headline cards for normal news; pick another story that has a photo
            if True:
                print(f"skip (no safe photo, trying another story): {headline}")
                shutil.rmtree(folder, ignore_errors=True)
                continue
            meta = {
                "headline": headline, "label": w["label"], "highlight": highlight,
                "caption": clean(w["caption"].rstrip()), "status": "needs_photo",
                "priority": int(w.get("priority") or 1),
                "ai_image": False, "created_at": now().isoformat(timespec="minutes"),
                "targets": ["facebook", "instagram"],
                "photo_hint": ", ".join(x for x in (w.get("photo_person"), w.get("image_query")) if x)
                              + f" ({why})",
                "sources_named": story["sources"],
                "source_links": [i["link"] for i in story["items"][:8]],
            }
            meta["issue"] = gh.create_photo_request_issue(post_id, meta)
            save_post(folder, meta)
            asked += 1
            made += 1
            _save_to_github(post_id)
            continue

        caption = clean(w["caption"].rstrip())
        if photo.get("ai_generated"):
            caption = add_ai_note(caption)
        elif photo.get("ai_enhanced"):
            from vok.words import AI_ENHANCED_NOTE
            caption = add_ai_note(caption, AI_ENHANCED_NOTE)
        if photo.get("credit"):
            caption += f"\n\n📸 {photo['credit']}"
        meta = {
            "headline": headline,
            "label": w["label"],
            "highlight": highlight,
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
        if not photo.get("text_card"):     # library photos are recorded too (no repeat within 7 days)
            st["photos"].append({"at": now().isoformat(), "page": photo["page"]})
        if telegram.enabled() and not (auto_approve or hold):
            telegram.send_for_approval(post_id, str(folder / "render.jpg"), meta)
        print(f"made {post_id}")
        made += 1
        save_state(st)
        _save_to_github(post_id)

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
