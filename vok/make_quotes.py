"""Quote posts: find strong, real, on-record statements in today's news and turn them into
VOK quote cards. Up to 5 a day.

Safety rules:
- the quote must appear word for word in the article text (no invented or reworded quotes)
- the speaker's photo must be Saad's library photo or a photo that really shows them (face check)
- the finished card goes through the same Gemini photo check as news posts
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime

from vok import collect, images
from vok.make_posts import _save_to_github
from vok.quote import render_quote
from vok.state import POSTS, all_posts, config, cycle_day, load_state, now, save_post, save_state, slug
from vok.words import AI_ENHANCED_NOTE, add_ai_note, clean
from vok.write import WriteError, _article_text, _gemini, check_photo

PER_DAY = 5

PROMPT = """You pick quotes for VOK, a news page for Pakistan and the Middle East.
From the ARTICLE TEXT below, find the single most striking DIRECT QUOTE: words a named
politician, official, military leader or famous person actually said, shown inside quotation
marks in the article. Prefer quotes that are bold, controversial, emotional or newsworthy.

Rules:
- "quote" must be copied EXACTLY from the article, word for word, 15 to 70 words. You may
  join two consecutive sentences of the same quote. Do not change, add or fix any word.
- "highlight": the last strong sentence or phrase of the quote, copied exactly from it.
- "speaker": the person's full name. "title": their role in a few words
  (e.g. "Iran's Foreign Minister", "U.S. President"). Never guess a title.
- No dashes of any kind anywhere.
- If the article has no such quote, return {{"ok": false}}.
- Also write "caption": a VOK caption: a short hook line, then 2 or 3 short paragraphs of
  context (who said it, where, when, why it matters, citing the outlet), then a question
  ending with 👇, then "Follow Vok for more stories like this.", then 5 hashtags starting
  with #Vok #VokOriginals. No dashes.

Return ONLY JSON: {{"ok": true, "quote": "...", "highlight": "...", "speaker": "...",
"title": "...", "caption": "...", "score": 1 to 10}}

HEADLINE: {headline}
OUTLET: {outlet}
ARTICLE TEXT:
{text}
"""


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def _quotes_today() -> int:
    today = cycle_day()
    return sum(1 for _, m in all_posts()
               if m.get("kind") == "quote" and m.get("created_at")
               and cycle_day(datetime.fromisoformat(m["created_at"])) == today
               and m.get("status") not in ("rejected",))


def main(count: int = 1) -> int:
    cfg = config()
    room = min(count, PER_DAY - _quotes_today())
    if room <= 0:
        print("quote limit for today reached")
        return 0
    st = load_state()
    used = set(st.get("quotes_used", []))
    stories = collect.top_stories(cfg, [], 30)
    made = 0
    for story in stories:
        if made >= room:
            break
        art = _article_text(story)
        if not art:
            continue
        outlet, text = art
        if text.count('"') + text.count("“") < 2:      # no quotation marks at all
            continue
        try:
            q = _gemini(PROMPT.format(headline=story["headline"], outlet=outlet, text=text[:5000]),
                        cfg["gemini_models"], budget_s=90)
        except (WriteError, Exception) as e:
            print(f"quote writer: {str(e)[:80]}")
            continue
        if not q.get("ok") or int(q.get("score", 0)) < 6:
            continue
        quote, speaker = q.get("quote", "").strip(), q.get("speaker", "").strip()
        n = len(quote.split())
        if not (15 <= n <= 75) or not speaker:
            continue
        if _norm(quote) not in _norm(text):                 # word for word, or nothing
            print(f"skip (quote not verbatim in article): {speaker}")
            continue
        key = _norm(speaker + " " + quote)[:120]
        if key in used:
            continue
        photo = images.library_photo(speaker, [], set())
        if not photo:
            found = images.best_photo([speaker], set(), "/tmp/qphoto", person=speaker)
            if found and found.get("query") == speaker:
                photo = found
        if not photo:
            print(f"skip (no photo of {speaker})")
            continue
        post_id = f"{now():%Y%m%d-%H%M}-quote-{slug(speaker)}"
        folder = POSTS / post_id
        folder.mkdir(parents=True, exist_ok=True)
        ext = photo["path"].rsplit(".", 1)[-1]
        shutil.copy(photo["path"], folder / f"photo.{ext}")
        cache = None
        if photo["page"].startswith("library:"):
            cache = images.LIBRARY / "cutouts" / (photo["page"][8:].rsplit(".", 1)[0] + ".png")
            cache.parent.mkdir(exist_ok=True)
        render_quote(quote, q.get("highlight", ""), speaker, q.get("title", ""),
                     str(folder / f"photo.{ext}"), str(folder / "render.jpg"), cache)
        if photo["page"].startswith("library:"):
            ok, why = True, "Saad's named library photo"
        else:   # a found photo: make sure it really is this person and fits
            ok, why = check_photo(str(folder / f"photo.{ext}"), f"Photo of {speaker}, {q.get('title', '')}",
                                  f"It must clearly show {speaker} alone. Quote: {quote[:200]}",
                                  cfg["gemini_models"])
        print(f"  speaker photo check: {'OK' if ok else 'REJECTED'} ({why})")
        if not ok:
            shutil.rmtree(folder, ignore_errors=True)
            continue
        caption = clean(q.get("caption", "").strip())
        if photo.get("ai_generated"):
            caption = add_ai_note(caption)
        elif photo.get("ai_enhanced"):
            caption = add_ai_note(caption, AI_ENHANCED_NOTE)
        if not photo["page"].startswith("library:"):
            caption += f"\n\n📸 {photo['credit']}"
        save_post(folder, {
            "kind": "quote", "headline": f"{speaker}: {quote[:80]}", "label": "QUOTE",
            "quote": quote, "speaker": speaker, "title": q.get("title", ""),
            "caption": caption, "status": "approved", "priority": 1,
            "created_at": now().isoformat(timespec="minutes"),
            "decided_at": now().isoformat(timespec="minutes"),
            "targets": ["facebook", "instagram"], "photo_page": photo["page"],
            "photo_credit": photo.get("credit", ""), "sources_named": [outlet],
            "source_links": [i["link"] for i in story["items"][:5]],
            "note": "quote verified word for word against the article text",
        })
        used.add(key)
        st["quotes_used"] = sorted(used)[-300:]
        save_state(st)
        _save_to_github(post_id)
        print(f"made quote: {speaker}")
        made += 1
    return made


if __name__ == "__main__":
    import sys
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
