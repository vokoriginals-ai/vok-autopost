"""Write the VOK headline + caption for a story with the free Gemini API.

Needs GEMINI_API_KEY. Gemini only sees the headlines/summaries we collected,
and is told to use nothing else, so it can't invent facts.
"""

from __future__ import annotations

import json
import os
import re

from vok import net

API = "https://generativelanguage.googleapis.com/v1beta"

STYLE = """You write Instagram/Facebook news posts for VOK (@vokoriginals), a fast-growing
news page. Audience: young South Asian and Middle Eastern readers. Focus: Middle East news and
globally trending stories, especially controversies. Goal: maximum engagement WITHOUT lying.

STRICT FACT RULES
- Use ONLY facts that appear in the SOURCE MATERIAL below. Never add numbers, names, quotes,
  dates or claims that are not there. If sources disagree, use the most cautious version.
- Attribute claims ("according to Reuters", "Iran's foreign ministry said").
- If the material is too thin or unclear to write 4 solid paragraphs, set "publishable": false.

PAKISTAN RULE
- If the story is mainly about Pakistan and is NOT major global news, set "publishable": false.

HEADLINE (goes on the image; this post is a SINGLE image, there is no next slide)
- 8 to 15 words. It must STATE the actual news: who did what, with the key fact.
  A reader who only sees the image must know what happened.
- Make it engaging with strong verbs, contrast, stakes and numbers that are in the sources,
  e.g. "Trump says he is ready to strike Iran after New Year if no deal is reached".
- NEVER tease or withhold: no "here's why", "here's who", "this is what", "find out",
  "you won't believe", "the real reason". Those are only for carousels, which this is not.
- No question marks, hashtags, emojis, or quotation marks around the whole headline.

CAPTION
- Line 1: a hook sentence (can include one relevant emoji).
- Then 4 to 6 short paragraphs (1–2 sentences each), most important fact first, with attribution.
- Then one question to the audience that invites comments (end with 👇).
- Then exactly: "Follow Vok for more stories like this."
- Then exactly 5 hashtags on one line: #Vok #VokOriginals plus 3 specific ones.
- Plain text, no markdown, no links. Total under 1,800 characters.

LABEL: "NEWS" for hard news, "VIRAL" for viral/social/celebrity stories.

PHOTO
- "image_query": 1–4 words to search Wikimedia Commons for a real photo that fits: a named
  person ("Benjamin Netanyahu"), a place ("Tehran", "Gaza City"), or an object ("oil tanker").
  Prefer a person's name when a leader is central.

Return ONLY JSON with these keys:
{"publishable": true/false, "reason": "...", "label": "NEWS|VIRAL", "headline": "...",
 "caption": "...", "image_query": "...", "image_query_backup": "...", "is_pakistan_story": true/false}
"""


TEASER = re.compile(r"(here'?s (why|who|what|how|the)|this is (why|what|how)|find out|"
                    r"you won'?t believe|the real reason|what happened next|\?)", re.I)


class WriteError(RuntimeError):
    pass


def _key() -> str:
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if not k:
        raise WriteError("GEMINI_API_KEY is not set (GitHub → Settings → Secrets).")
    return k


def _available_flash_models() -> list[str]:
    try:
        data = net.get_json(f"{API}/models", {"key": _key(), "pageSize": 200})
    except Exception:
        return []
    names = [m["name"].split("/", 1)[1] for m in data.get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])
             and "flash" in m["name"] and "image" not in m["name"] and "tts" not in m["name"]]
    return sorted(names, reverse=True)


def _gemini(prompt: str, models: list[str]) -> dict:
    tried = []
    for model in models + _available_flash_models():
        if model in tried:
            continue
        tried.append(model)
        try:
            data = net.post_json(
                f"{API}/models/{model}:generateContent",
                {"contents": [{"parts": [{"text": prompt}]}],
                 "generationConfig": {"responseMimeType": "application/json",
                                      "temperature": 0.7}},
                headers={"x-goog-api-key": _key()})
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            text = re.sub(r"^```(json)?|```$", "", text.strip()).strip()
            return json.loads(text)
        except net.HTTPError as e:
            print(f"gemini {model}: {e}")
            if e.status in (401, 403):
                raise WriteError(f"Gemini key rejected: {e}") from None
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            print(f"gemini {model}: bad response {e}")
    raise WriteError(f"No Gemini model worked (tried {', '.join(tried)}).")


def write_post(story: dict, models: list[str]) -> dict:
    material = "\n".join(
        f"- [{i['source']}] {i['title']}" + (f" — {i['summary']}" if i["summary"] else "")
        for i in story["items"][:12])
    prompt = f"{STYLE}\n\nSOURCE MATERIAL ({len(story['sources'])} outlets):\n{material}\n"
    out = _gemini(prompt, models)
    for k in ("headline", "caption", "label"):
        if out.get("publishable") and not out.get(k):
            out["publishable"] = False
            out["reason"] = f"missing {k}"
    if out.get("publishable") and TEASER.search(out.get("headline", "")):
        out["publishable"] = False
        out["reason"] = f"teaser headline not allowed on single posts: {out['headline']}"
    out["label"] = "VIRAL" if str(out.get("label", "")).upper() == "VIRAL" else "NEWS"
    return out
