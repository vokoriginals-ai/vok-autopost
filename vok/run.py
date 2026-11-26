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
    render(str(photo), meta["headline"], str(out), meta.get("label", "NEWS"), focus,
           highlight=meta.get("highlight", ""))
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


def do_repost(post_id: str) -> bool:
    """Delete the old Facebook copy (Saad deletes Instagram himself), then publish again."""
    from vok import net
    from vok.publish import GRAPH, _token
    folder, meta = load_post(post_id)
    fb = ((meta.get("old_result") or {}).get("facebook") or {}).get("post_id")
    if fb and not meta.get("old_fb_deleted"):
        try:
            req = net.urllib.request.Request(f"{GRAPH}/{fb}?access_token={_token()}", method="DELETE")
            print("facebook delete:", net.urllib.request.urlopen(req, timeout=30).read()[:100])
        except Exception as e:
            print(f"facebook delete failed: {str(e)[:150]}")
            return False
        meta["old_fb_deleted"] = True
        save_post(folder, meta)
    meta["status"] = "approved"
    save_post(folder, meta)
    return do_publish(post_id)


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


def _sync() -> None:
    """Save local changes and take everyone else's. On a clash the version already on
    GitHub wins (a pause or fix made there must never be overwritten)."""
    import os
    os.system('git add posts data >/dev/null 2>&1; git commit -qm "drip: update posts [skip ci]" >/dev/null 2>&1; '
              '(git pull -q --rebase -X ours || git rebase --abort); git push -q')


def drip(max_hours: float = 5.5) -> None:
    """Keep running: every 5 min read replies, auto-approve, and publish the next post
    when it is due. Posts are spread evenly so the queue lasts until the window ends
    (gap 30 to 60 min). After ~5.5 h it starts a fresh copy of itself (GitHub limit 6 h)."""
    import json, os, time, urllib.request
    from datetime import datetime, timedelta
    from vok import tick
    from vok.state import all_posts, config, in_window, load_state, save_state
    started = time.time()
    last_news = 0.0
    last_quote = time.time() - 7200     # first quote ~30 min after start
    def beat():
        # heartbeat: "a publisher is alive" for the next 20 minutes only, so a crashed
        # run can never block the others for hours
        s = load_state()
        s["drip_until"] = (now() + timedelta(minutes=20)).isoformat()
        save_state(s)
        return s["drip_until"]
    st0 = {"drip_until": beat()}
    while time.time() - started < max_hours * 3600:
      try:
        st0["drip_until"] = (now() + timedelta(minutes=20)).isoformat()
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
            # hourly: look for new stories too (GitHub's own timer isn't reliable)
            if time.time() - last_news > 1200 and os.environ.get("GEMINI_API_KEY"):
                last_news = time.time()
                try:
                    from vok import make_posts
                    make_posts.main(count=3)
                except Exception as e:
                    print(f"news check failed: {str(e)[:120]}")
            _sync()                      # get the latest edits BEFORE deciding anything
            # quote cards: one every ~2.5 hours, up to 5 a day
            if time.time() - last_quote > 9000 and os.environ.get("GEMINI_API_KEY"):
                last_quote = time.time()
                try:
                    from vok import make_quotes
                    make_quotes.main(1)
                except Exception as e:
                    print(f"quote check failed: {str(e)[:120]}")
            st = load_state()
            st["drip_until"] = st0["drip_until"]
            tick.apply_decisions(st)
            tick.auto_approve(cfg)
            tick.expire_old()
            tick.publish_next(cfg, st)
            save_state(st)
            _sync()
        else:
            print("outside posting hours: waiting")        # public repo: running is free
        # daily report at 10am PKT, once per day
        try:
            stp = load_state()
            today = t.strftime("%Y-%m-%d")
            if t.hour >= 10 and t.hour < 12 and stp.get("report_sent") != today:
                from vok import report
                report.send(22)
                stp["report_sent"] = today
                save_state(stp)
                _sync()
        except Exception as e:
            print(f"report failed: {str(e)[:150]}")
      except Exception as e:                 # never let one error stop the publisher
        print(f"loop error (continuing): {type(e).__name__}: {str(e)[:150]}")
      time.sleep(300)
    # hand over to a fresh run so the queue keeps going
    if True:                       # always hand over: the publisher never stops
        repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
        if repo and token:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{repo}/actions/workflows/tick.yml/dispatches",
                data=json.dumps({"ref": "main", "inputs": {"drip": "yes"}}).encode(), method="POST",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                         "User-Agent": "vok-autopost"})
            for wait in (0, 15, 45, 90, 180, 300, 600):     # GitHub sometimes answers 500
                time.sleep(wait)
                try:
                    urllib.request.urlopen(req, timeout=30)
                    print("handed over to a new drip run")
                    break
                except Exception as e:
                    print(f"handover failed ({str(e)[:80]}), retrying")
            else:
                print("handover failed: the watchdog will restart the publisher")


if __name__ == "__main__":
    if sys.argv[1:2] == ["drip"]:
        drip()
        sys.exit(0)
    if len(sys.argv) >= 2 and sys.argv[1] == "publish-all":
        gap = int(sys.argv[2]) if len(sys.argv) > 2 else 180
        sys.exit(0 if publish_all_approved(gap) else 1)
    if len(sys.argv) >= 3 and sys.argv[1] == "tokencheck":
        from vok import net
        from vok.publish import GRAPH, PAGE_ID, IG_ID, _token
        for path, fields in [("me", "id,name"), (PAGE_ID, "name"), (IG_ID, "username")]:
            try:
                print(path, net.get_json(f"{GRAPH}/{path}", {"fields": fields, "access_token": _token()}))
            except Exception as e:
                print(path, "ERROR", str(e)[:300])
        sys.exit(0)
    if len(sys.argv) >= 3 and sys.argv[1] == "igsource":
        from vok import collect
        from datetime import datetime, timezone
        handle, _, word = sys.argv[2].partition(":")
        for it in collect._instagram({"name": "test", "instagram": handle, "limit": 100}, datetime.now(timezone.utc), 24 * 8):
            if not word or word.lower() in (it["title"] + " " + it["summary"]).lower():
                print(it["published"][:16], it["title"][:110], it["link"])
        sys.exit(0)
    if len(sys.argv) >= 3 and sys.argv[1] == "rephoto":
        # rephoto "post_id|person|query1;query2;query3" ... : find a safe real photo, render,
        # Gemini check; approve on success, reject (never a headline card) on failure
        import re as _re, shutil as _sh
        from vok import images
        from vok.render import render
        from vok.write import check_photo
        from vok.state import config as _cfg, load_state, save_state
        st = load_state()
        used = {u["page"] for u in st.setdefault("photos", [])}
        for spec in sys.argv[2:]:
            pid, person, qs = (spec.split("|") + ["", ""])[:3]
            folder, meta = load_post(pid)
            queries = [q for q in qs.split(";") if q]
            got = None
            for qset, generic in (([person] + queries if person else queries, False), (queries, True)):
                cand = images.best_photo(qset, exclude=used, workdir=str(folder / "_c"),
                                         person=person if not generic else "", generic=generic)
                if not cand:
                    continue
                for x in folder.glob("photo.*"):
                    x.unlink()
                _sh.copy(cand["path"], folder / "photo.jpg")
                render(str(folder / "photo.jpg"), meta["headline"], str(folder / "render.jpg"),
                       meta.get("label", "NEWS"), highlight=meta.get("highlight", ""))
                from vok.render import face_visible
                if person and not generic and not face_visible(str(folder / "render.jpg")):
                    print(pid, "check: False (face not fully visible)")
                    used.add(cand["page"])
                    continue
                ok, why = check_photo(str(folder / "render.jpg"), meta["headline"], meta["caption"][:600],
                                      _cfg()["gemini_models"])
                print(pid, "check:", ok, why, cand["credit"])
                if ok:
                    got = cand
                    break
                used.add(cand["page"])
            _sh.rmtree(folder / "_c", ignore_errors=True)
            if got:
                cap = _re.sub(r"\n\n📸 [^\n]*", "", meta["caption"]).rstrip()
                meta.update(caption=cap + f"\n\n📸 {got['credit']}", photo_credit=got["credit"],
                            photo_page=got["page"], status="approved", decided_at=now().isoformat(timespec="minutes"),
                            note="real photo found by rephoto")
                st["photos"].append({"at": now().isoformat(), "page": got["page"]})
            elif meta.get("label") == "BREAKING":
                from vok.render import render_text_card
                for x in folder.glob("photo.*"):
                    x.unlink()
                render_text_card(meta["headline"], str(folder / "render.jpg"), "BREAKING",
                                 meta.get("highlight", ""))
                meta["caption"] = _re.sub(r"\n\n📸 [^\n]*", "", meta["caption"]).rstrip()
                meta.update(status="approved", photo_page="text-card", photo_credit="",
                            note="breaking: no fitting photo, headline card")
            else:
                meta.update(status="rejected", note="no safe real photo found (headline cards only for breaking)")
            save_post(folder, meta)
            print(pid, "->", meta["status"])
        save_state(st)
        sys.exit(0)
    if len(sys.argv) >= 3 and sys.argv[1] == "check":
        from vok.write import check_photo
        from vok.state import config as _cfg
        for pid in sys.argv[2].split(","):
            f, m = load_post(pid)
            print(pid, check_photo(str(f / "render.jpg"), m["headline"], m["caption"][:600], _cfg()["gemini_models"]))
        sys.exit(0)
    if len(sys.argv) >= 3 and sys.argv[1] == "repost":
        sys.exit(0 if do_repost(sys.argv[2]) else 1)
    if len(sys.argv) < 3 or sys.argv[1] not in ("render", "publish"):
        sys.exit(__doc__)
    if sys.argv[1] == "render":
        do_render(sys.argv[2])
    else:
        sys.exit(0 if do_publish(sys.argv[2]) else 1)
