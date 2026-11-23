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


def decisions() -> list[tuple[str, int, str]]:
    """[(decision 'ok'/'no', issue_number, post_id), ...] from the owner's replies."""
    issues = _req("GET", f"/issues?state=open&labels={LABEL}&per_page=100") or []
    out = []
    for iss in issues:
        m = re.search(r"post-id: ([\w\-]+)", iss.get("body") or "")
        if not m:
            continue
        for c in _req("GET", f"/issues/{iss['number']}/comments?per_page=50") or []:
            if (c.get("user") or {}).get("login", "").lower() != owner().lower():
                continue
            w = _first_word(c.get("body", ""))
            if w in YES or w in NO:
                out.append(("ok" if w in YES else "no", iss["number"], m.group(1)))
                break
    return out
