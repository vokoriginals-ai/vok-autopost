"""Nightly performance report: how each VOK post of the last cycle did on Instagram
and Facebook, sent to Saad as a GitHub issue (GitHub emails him)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from vok import gh, net
from vok.publish import GRAPH, IG_ID, PAGE_ID, _token


def _ig_posts(hours: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    data = net.get_json(f"{GRAPH}/{IG_ID}/media", {
        "fields": "caption,timestamp,like_count,comments_count,permalink,media_product_type",
        "limit": 60, "access_token": _token()}).get("data", [])
    out = []
    for m in data:
        ts = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        if ts < cutoff:
            continue
        reach = saves = shares = None
        try:
            ins = net.get_json(f"{GRAPH}/{m['id']}/insights",
                               {"metric": "reach,saved,shares", "access_token": _token()}).get("data", [])
            v = {i["name"]: (i.get("values") or [{}])[0].get("value", i.get("total_value", {}).get("value"))
                 for i in ins}
            reach, saves, shares = v.get("reach"), v.get("saved"), v.get("shares")
        except Exception as e:
            print(f"insights failed for {m['id']}: {str(e)[:100]}")
        title = ((m.get("caption") or "").strip().splitlines() or [""])[0][:80]
        out.append({"time": ts, "title": title, "likes": m.get("like_count", 0),
                    "comments": m.get("comments_count", 0), "reach": reach, "saves": saves,
                    "shares": shares, "link": m.get("permalink", "")})
    return out


def _fb_posts(hours: int) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    data = net.get_json(f"{GRAPH}/{PAGE_ID}/posts", {
        "fields": "message,created_time,permalink_url,reactions.summary(true).limit(0),"
                  "comments.summary(true).limit(0),shares",
        "limit": 60, "access_token": _token()}).get("data", [])
    out = []
    for m in data:
        ts = datetime.strptime(m["created_time"], "%Y-%m-%dT%H:%M:%S%z")
        if ts < cutoff:
            continue
        out.append({"title": ((m.get("message") or "").strip().splitlines() or [""])[0][:80],
                    "reactions": m.get("reactions", {}).get("summary", {}).get("total_count", 0),
                    "comments": m.get("comments", {}).get("summary", {}).get("total_count", 0),
                    "shares": (m.get("shares") or {}).get("count", 0)})
    return out


def build(hours: int = 24) -> str:
    pkt = timezone(timedelta(hours=5))
    ig = sorted(_ig_posts(hours), key=lambda r: ((r["reach"] or 0), r["likes"]), reverse=True)
    fb = sorted(_fb_posts(hours), key=lambda r: r["reactions"] + r["comments"] * 2 + r["shares"] * 3,
                reverse=True)
    lines = [f"## 📊 VOK daily report: last {hours} hours", ""]
    if ig:
        tot_reach = sum(r["reach"] or 0 for r in ig)
        tot_likes = sum(r["likes"] for r in ig)
        lines += [f"**Instagram:** {len(ig)} posts, {tot_reach:,} total reach, {tot_likes:,} likes", "",
                  "| # | Time | Post | Reach | Likes | Comments | Saves | Shares |",
                  "|---|---|---|---|---|---|---|---|"]
        for i, r in enumerate(ig, 1):
            t = r["time"].astimezone(pkt).strftime("%d %b %H:%M")
            title = r["title"].replace("|", " ")
            lines.append(f"| {i} | {t} | [{title}]({r['link']}) | {r['reach'] if r['reach'] is not None else '?'} "
                         f"| {r['likes']} | {r['comments']} | {r['saves'] if r['saves'] is not None else '?'} "
                         f"| {r['shares'] if r['shares'] is not None else '?'} |")
        lines += ["", f"🏆 **Best:** {ig[0]['title']}", f"📉 **Weakest:** {ig[-1]['title']}", ""]
    if fb:
        lines += [f"**Facebook:** {len(fb)} posts, "
                  f"{sum(r['reactions'] for r in fb):,} reactions, {sum(r['comments'] for r in fb):,} comments, "
                  f"{sum(r['shares'] for r in fb):,} shares", "",
                  "Top 5 on Facebook:"]
        for r in fb[:5]:
            lines.append(f"- {r['title']} ({r['reactions']} reactions, {r['comments']} comments, {r['shares']} shares)")
    if not ig and not fb:
        lines.append("No posts found in this period.")
    return "\n".join(lines)


def send(hours: int = 24) -> int | None:
    body = build(hours)
    print(body)
    if not gh.enabled():
        return None
    day = datetime.now(timezone(timedelta(hours=5))).strftime("%d %b %Y")
    res = gh._req("POST", "/issues", {"title": f"[VOK 📊 report] {day}",
                                      "body": f"@{gh.owner()}\n\n{body}"})
    num = res.get("number") if res else None
    if num:
        gh.close(num)          # GitHub has already emailed it; keep the issue list clean
    return num


if __name__ == "__main__":
    import sys
    send(int(sys.argv[1]) if len(sys.argv) > 1 else 24)
