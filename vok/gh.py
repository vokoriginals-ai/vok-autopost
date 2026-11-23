"""Email approvals through GitHub Issues.

Each new post becomes an issue in this repo. GitHub emails the owner
(vokoriginals-ai) about it. The owner replies to that email — or comments in
the GitHub app — with "ok" or "no". Only comments from the repo owner count.

Uses the GITHUB_TOKEN that GitHub Actions provides automatically.
Standard library only.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

API = "https://api.github.com"
LABEL = "vok-pending"

YES = {"ok", "okay", "yes", "y", "approve", "approved", "go", "post", "✅", "👍"}
NO = {"no", "n", "reject", "rejected", "skip", "❌", "👎"}


def enabled() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPOSITORY"))


def owner() -> str:
    return os.environ["GITHUB_REPOSITORY"].split("/")[0]


def _req(method: str, path: str, payload: dict | None = None):
    url = f"{API}/repos/{os.environ['GITHUB_REPOSITORY']}{path}"
    req = urllib.request.Request(
        url, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "User-Agent": "vok-autopost"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        print(f"github {method} {path} failed: {e.code} {e.read()[:200]!r}")
        return None


def ensure_label() -> None:
    if _req("GET", f"/labels/{LABEL}") is None:
        _req("POST", "/labels", {"name": LABEL, "color": "f9d71c",
                                 "description": "VOK post waiting for approval"})


def create_post_issue(post_id: str, meta: dict, image_url: str | None) -> int | None:
    src = ", ".join(meta.get("sources_named", [])[:8])
    img = f"![post]({image_url})\n\n" if image_url else \
        f"![post](../blob/main/posts/{post_id}/render.jpg?raw=true)\n\n"
    body = (
        f"@{owner()} new {meta['label']} post waiting for you.\n\n"
        f"{img}"
        f"**Headline:** {meta['headline']}\n\n"
        f"**Caption:**\n\n```\n{meta['caption']}\n```\n\n"
        f"**Sources:** {src}\n\n"
        f"---\n"
        f"### Reply to this email with one word\n"
        f"- **ok** → approve (it posts in the next free slot)\n"
        f"- **no** → reject\n\n"
        f"<sub>post-id: {post_id}</sub>"
    )
    res = _req("POST", "/issues", {"title": f"[VOK] {meta['headline'][:110]}",
                                   "body": body, "labels": [LABEL]})
    return res.get("number") if res else None


def comment(number: int, text: str) -> None:
    _req("POST", f"/issues/{number}/comments", {"body": text})


def close(number: int, text: str | None = None) -> None:
    if text:
        comment(number, text)
    _req("PATCH", f"/issues/{number}", {"state": "closed"})
    _req("DELETE", f"/issues/{number}/labels/{LABEL}")


def _first_word(body: str) -> str:
    for line in (body or "").splitlines():
        line = line.strip()
        if not line or line.startswith(">"):        # skip quoted email text
            continue
        word = re.split(r"[\s,.!]+", line.lower())[0]
        return word
    return ""


IMG = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)|<img[^>]+src=\"(https?://[^\"]+)\"")


def decisions() -> list[tuple[str, int, str, str | None]]:
    """[(decision 'ok'/'no', issue_number, post_id, attached_image_url), ...] from the owner's replies."""
    issues = _req("GET", f"/issues?state=open&labels={LABEL}&per_page=100") or []
    out = []
    for iss in issues:
        m = re.search(r"post-id: ([\w\-]+)", iss.get("body") or "")
        if not m:
            continue
        decision, image = None, None
        for c in _req("GET", f"/issues/{iss['number']}/comments?per_page=50") or []:
            if (c.get("user") or {}).get("login", "").lower() != owner().lower():
                continue
            body = c.get("body", "")
            for a, b in IMG.findall(body):
                image = a or b                      # newest attached photo wins
            w = _first_word(body)
            if decision is None and (w in YES or w in NO):
                decision = "ok" if w in YES else "no"
        if decision:
            out.append((decision, iss["number"], m.group(1), image))
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def download(url: str, path: str) -> None:
    """Download a photo attached to an issue (private repo: needs the token,
    but the storage link it redirects to must be fetched without it)."""
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "User-Agent": "vok-autopost"})
    try:
        r = urllib.request.build_opener(_NoRedirect).open(req, timeout=60)
        data = r.read()
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308):
            raise
        loc = e.headers["Location"]
        with urllib.request.urlopen(urllib.request.Request(
                loc, headers={"User-Agent": "vok-autopost"}), timeout=60) as r2:
            data = r2.read()
    with open(path, "wb") as f:
        f.write(data)


def create_photo_request_issue(post_id: str, meta: dict) -> int | None:
    src = ", ".join(meta.get("sources_named", [])[:8])
    body = (
        f"@{owner()} 📷 **No safe free photo found for this story.**\n\n"
        f"**Headline:** {meta['headline']}\n\n"
        f"**Photo idea:** {meta.get('photo_hint') or 'any fitting news photo'}\n\n"
        f"**Caption:**\n\n```\n{meta['caption']}\n```\n\n"
        f"**Sources:** {src}\n\n"
        f"---\n"
        f"### To post it\n"
        f"Open this issue in the GitHub app or website, write **ok**, attach a photo, and send. "
        f"(Email replies drop attachments.) Add a credit line after ok if you want one, "
        f"e.g. `ok credit: Reuters`.\n\n"
        f"- **no** → skip this story\n\n"
        f"<sub>post-id: {post_id}</sub>"
    )
    res = _req("POST", "/issues", {"title": f"[VOK 📷 photo needed] {meta['headline'][:90]}",
                                   "body": body, "labels": [LABEL]})
    return res.get("number") if res else None


def credit_from_replies(number: int) -> str | None:
    for c in _req("GET", f"/issues/{number}/comments?per_page=50") or []:
        if (c.get("user") or {}).get("login", "").lower() != owner().lower():
            continue
        m = re.search(r"credit:\s*([^\n]+)", c.get("body", ""), re.I)
        if m:
            return IMG.sub("", m.group(1)).strip()[:80] or None
    return None
