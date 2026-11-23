"""Make new posts: find stories → write with Gemini → find photo → design →
send to Telegram for approval. Runs a few times a day from GitHub.
"""

from __future__ import annotations

import sys
from datetime import timedelta

from vok import collect, images, telegram
from vok.render import render
from vok.state import (all_posts, config, load_state, now, save_post, save_state, slug,
                       POSTS)
from vok.write import WriteError, write_post


def main() -> int:
    cfg = config()
    st = load_state()
    today = now().date().isoformat()

    made_today = sum(1 for _, m in all_posts() if m.get("created_at", "").startswith(today))
    room = min(cfg["posts_per_run"], cfg["posts_per_day"] - made_today)
    if room <= 0:
        print(f"daily limit reached ({made_today} made today)")
        return 0

    recent = (now() - timedelta(days=2)).isoformat()
    seen = [s["words"] for s in st["seen"] if s.get("at", "") >= recent]
    stories = collect.top_stories(cfg, seen, limit=room * 3)
    print(f"{len(stories)} candidate stories, room for {room}")

    made = 0
    for story in stories:
        if made >= room:
            break
        st["seen"].append({"at": now().isoformat(), "words": sorted(story["words"]),
                           "headline": story["headline"]})
        try:
            w = write_post(story, cfg["gemini_models"])
        except WriteError as e:
            print(f"writer error: {e}")
            break
        if not w.get("publishable"):
            print(f"skip: {story['headline'][:70]} – {w.get('reason')}")
            continue

        used = {u["page"] for u in st.setdefault("photos", [])}
        photo = images.find_photo(w.get("image_query", ""), w.get("image_query_backup", ""),
                                  exclude=used)
        if not photo:
            print(f"skip (no free photo): {w['headline']}")
            continue

        post_id = f"{now():%Y%m%d-%H%M}-{slug(w['headline'])}"
        folder = POSTS / post_id
        folder.mkdir(parents=True, exist_ok=True)
        try:
            images.download(photo["url"], str(folder / "photo.jpg"))
            render(str(folder / "photo.jpg"), w["headline"], str(folder / "render.jpg"),
                   w["label"])
        except Exception as e:
            print(f"skip (photo/render failed): {e}")
            continue

        caption = w["caption"].rstrip() + f"\n\n📸 {photo['credit']}"
        meta = {
            "headline": w["headline"],
            "label": w["label"],
            "caption": caption,
            "status": "pending",
            "created_at": now().isoformat(timespec="minutes"),
            "targets": ["facebook", "instagram"],
            "photo_credit": photo["credit"],
            "photo_page": photo["page"],
            "sources_named": story["sources"],
            "source_links": [i["link"] for i in story["items"][:8]],
        }
        save_post(folder, meta)
        st["photos"].append({"at": now().isoformat(), "page": photo["page"]})
        if telegram.enabled():
            telegram.send_for_approval(post_id, str(folder / "render.jpg"), meta)
        print(f"made {post_id}")
        made += 1

    save_state(st)
    print(f"done: {made} new posts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
