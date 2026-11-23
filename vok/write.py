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
- Use the ARTICLE TEXT (when given) for facts. If the material is too thin to write at least
  3 short factual paragraphs, set "publishable": false. For breaking news (priority 3) 2
  paragraphs of confirmed facts is enough: say clearly what is confirmed and what is not yet.

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

NO DASHES ANYWHERE (headline and caption): never use em dashes (—), en dashes (–) or hyphens (-).
Use commas, full stops or "and" instead; write "US Iran talks", "pro Israel", "7 year".

CAPTION
- Line 1: a hook sentence (can include one relevant emoji).
- Then 3 to 6 short paragraphs (1–2 sentences each), most important fact first, with attribution.
- Then one question to the audience that invites comments (end with 👇).
- Then exactly: "Follow Vok for more stories like this."
- Then exactly 5 hashtags on one line: #Vok #VokOriginals plus 3 specific ones.
- Plain text, no markdown, no links. Total under 1,800 characters.

TOPIC FIT: VOK's audience is Pakistan and the Middle East. Set "publishable": false for local
sports deals and results (baseball, American football, college sports, routine tennis or golf
results), celebrity gossip with no wider angle, and local business news. Global sports moments
(World Cup, Olympics, cricket, a Muslim athlete's historic win) are fine.

PRIORITY: "priority": 3 = breaking news (just happened, big: war moves, strikes, deaths of
leaders, major disasters, huge political shocks), 2 = important, 1 = normal/viral.

LABEL: "NEWS" for hard news, "VIRAL" for viral/social/celebrity stories.

PHOTO (who or what the picture shows)
- "photo_person": the full name of the person the picture should show, chosen in this order:
  1. the person who made the statement, warning, threat or decision in the headline
     (Iran's spokesman warns → that spokesman; Trump threatens → Donald Trump);
  2. otherwise the person the story is mainly about;
  3. otherwise, if the story is about a country's government, army or policy, that country's
     current head of state or head of government (Iran → Supreme Leader or President, Israel →
     Benjamin Netanyahu). Use the name as of today's date.
  BUT for military actions, attacks, accidents, disasters, protests and other EVENTS where no
  named person spoke, set "photo_person" to "" and describe the event in "image_query"
  (shot down drone → "military drone"; flood → "flood rescue"; strike → "airstrike smoke").
  Use the leader only for government statements, decisions, deals and policy.
  Use "" also when no person fits (an earthquake, a company result with no leader named...).
- "image_query": 1–4 words for a backup photo of the place or object (e.g. "Strait of Hormuz",
  "Gaza City", "US Capitol").
- "image_query_backup": a second, different backup query.

Return ONLY JSON with these keys:
{"publishable": true/false, "reason": "...", "label": "NEWS|VIRAL", "headline": "...",
 "caption": "...", "photo_person": "...", "priority": 1, "image_query": "...", "image_query_backup": "...", "is_pakistan_story": true/false}
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


_DEAD: set[str] = set()      # models that don't exist for this key (404)
_GOOD: list[str] = []        # the model that worked last time is tried first


def _gemini(prompt: str, models: list[str], budget_s: int = 180) -> dict:
    import time
    deadline = time.time() + budget_s          # one story never blocks the batch for long
    order: list[str] = []
    for m in _GOOD + models + _available_flash_models():
        if m not in order and m not in _DEAD:
            order.append(m)
    for model in order[:8]:
        for attempt in range(3):
            if time.time() > deadline:
                raise WriteError("Gemini is busy right now (took too long).")
            try:
                data = net.post_json(
                    f"{API}/models/{model}:generateContent",
                    {"contents": [{"parts": [{"text": prompt}]}],
                     "generationConfig": {"responseMimeType": "application/json",
                                          "temperature": 0.7}},
                    headers={"x-goog-api-key": _key()}, timeout=45)
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                text = re.sub(r"^```(json)?|```$", "", text.strip()).strip()
                result = json.loads(text)
                if model in _GOOD:
                    _GOOD.remove(model)
                _GOOD.insert(0, model)
                return result
            except net.HTTPError as e:
                if e.status in (401, 403):
                    raise WriteError(f"Gemini key rejected: {e}") from None
                if e.status == 404:
                    _DEAD.add(model)
                    break
                if e.status == 503 and attempt < 2:      # busy: wait and retry same model
                    wait = 20 * (attempt + 1)
                    print(f"gemini {model}: busy, retrying in {wait}s")
                    time.sleep(wait)
                    continue
                print(f"gemini {model}: HTTP {e.status}")
                break                                     # 429 / other: next model
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                print(f"gemini {model}: bad response {e}")
                break
            except (TimeoutError, OSError) as e:          # slow network / timeout
                print(f"gemini {model}: network problem ({str(e)[:60]}), trying again")
                time.sleep(5)
                continue
    raise WriteError("Gemini is busy right now (all models refused).")


def _article_text(story: dict) -> tuple[str, str] | None:
    """Read the body of one real article about the story (direct outlet links only;
    Google News links are redirects we can't follow cheaply)."""
    import html as _html
    for it in story["items"]:
        link = it.get("link", "")
        if not link or "news.google.com" in link:
            continue
        try:
            raw = net.get(link, timeout=20).decode("utf-8", "replace")
        except Exception:
            continue
        raw = re.sub(r"<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
        body = re.search(r"<article[^>]*>(.*?)</article>", raw, re.S | re.I)
        raw = body.group(1) if body else raw
        paras = re.findall(r"<p[\s>](?:[^>]*>)?((?:(?!<p[\s>]).)*?)</p>", raw, re.S | re.I)
        clean = [re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", "", x))).strip() for x in paras]
        # real sentences only: skips menus, buttons and captions
        text = " ".join(x for x in clean if len(x) > 80 and "." in x)
        text = re.sub(r"\s+", " ", text)
        if len(text) > 600:
            return it["source"], text[:5000]
    return None


def write_post(story: dict, models: list[str]) -> dict:
    material = "\n".join(
        f"- [{i['source']}] {i['title']}" + (f" — {i['summary']}" if i["summary"] else "")
        for i in story["items"][:12])
    article = _article_text(story)
    prompt = f"{STYLE}\n\nSOURCE MATERIAL ({len(story['sources'])} outlets):\n{material}\n"
    if article:
        prompt += f"\nARTICLE TEXT (from {article[0]}):\n{article[1]}\n"
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


PHOTO_CHECK = """You are the photo editor of VOK, a news page. Look at this finished post image.
Headline: {headline}
Story: {summary}

Reject the photo (ok=false) if ANY of these is true:
- it shows a different person than the story is about, or a person unrelated to the story
- the scene does not match the story (e.g. a petrol station for a bus crash, a mountain for a
  military story, soldiers of another country, a random building)
- it is a screenshot, a social media post, a chart, a graph, an infographic or a document
- it contains offensive words, swear words or hateful text
- the mood is wrong for the story (someone smiling on a story about deaths, war or genocide)
- it is blurry, distorted, or the main subject is cut off
- it could mislead readers about what happened
Otherwise ok=true. A general photo of the right place, the right type of object or the right
person is fine. Return ONLY JSON: {{"ok": true/false, "reason": "short reason"}}"""


def check_photo(image_path: str, headline: str, summary: str, models: list[str]) -> tuple[bool, str]:
    """Gemini vision check of the finished design. Fails closed: no answer = not ok."""
    import base64, time
    data = base64.b64encode(open(image_path, "rb").read()).decode()
    prompt = PHOTO_CHECK.format(headline=headline, summary=summary[:600])
    order = [m for m in _GOOD + models + _available_flash_models() if m not in _DEAD]
    seen = []
    for model in order:
        if model in seen:
            continue
        seen.append(model)
        if len(seen) > 6:
            break
        try:
            out = net.post_json(
                f"{API}/models/{model}:generateContent",
                {"contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg", "data": data}},
                                         {"text": prompt}]}],
                 "generationConfig": {"responseMimeType": "application/json", "temperature": 0}},
                headers={"x-goog-api-key": _key()}, timeout=60)
            text = out["candidates"][0]["content"]["parts"][0]["text"]
            res = json.loads(re.sub(r"^```(json)?|```$", "", text.strip()).strip())
            return bool(res.get("ok")), str(res.get("reason", ""))[:200]
        except Exception as e:
            print(f"photo check {model}: {str(e)[:80]}")
            time.sleep(30 if "429" in str(e) else 3)     # free-tier limit resets within a minute
    return False, "photo check unavailable"
