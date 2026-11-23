"""Telegram approvals: each new post is sent to Saad with ✅ / ❌ buttons.

Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. Only button taps coming
from TELEGRAM_CHAT_ID are accepted; everything else is ignored.
Standard library only.
"""

from __future__ import annotations

import json
import os

from vok import net


def _env():
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return tok, chat


def enabled() -> bool:
    tok, chat = _env()
    return bool(tok and chat)


def _api(method: str, data: dict, files: dict | None = None) -> dict:
    tok, _ = _env()
    url = f"https://api.telegram.org/bot{tok}/{method}"
    try:
        if files:
            return net.post_multipart(url, data, files)
        return net.post_form(url, data)
    except net.HTTPError as e:      # never let a Telegram hiccup stop publishing
        print(f"telegram {method} failed: {e}")
        return {"ok": False}


def send_text(text: str, buttons: list | None = None) -> dict:
    _, chat = _env()
    data = {"chat_id": chat, "text": text[:4000], "disable_web_page_preview": "true"}
    if buttons:
        data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    return _api("sendMessage", data)


def send_for_approval(post_id: str, image_path: str, meta: dict) -> None:
    _, chat = _env()
    sources = ", ".join(meta.get("sources_named", [])[:6])
    short = f"🆕 {meta['label']} · {meta['headline']}\n\nSources: {sources}"
    with open(image_path, "rb") as fh:
        _api("sendPhoto", {"chat_id": chat, "caption": short[:1000]},
             {"photo": ("post.jpg", fh.read(), "image/jpeg")})
    send_text(
        f"{meta['caption']}\n\n— — —\nPhoto: {meta.get('photo_credit', '?')}\nID: {post_id}",
        buttons=[[{"text": "✅ Approve", "callback_data": f"ok:{post_id}"[:64]},
                  {"text": "❌ Reject", "callback_data": f"no:{post_id}"[:64]}]])


def fetch_decisions(offset: int) -> tuple[list[tuple[str, str]], int]:
    """Return ([(decision, post_id), ...], new_offset). decision is 'ok' or 'no'."""
    tok, chat = _env()
    try:
        data = net.get_json(f"https://api.telegram.org/bot{tok}/getUpdates",
                            {"offset": offset, "timeout": 0,
                             "allowed_updates": json.dumps(["callback_query"])})
    except net.HTTPError as e:
        print(f"telegram getUpdates failed: {e}")
        return [], offset
    decisions = []
    for upd in data.get("result", []):
        offset = max(offset, upd["update_id"] + 1)
        cq = upd.get("callback_query")
        if not cq:
            continue
        if str(cq.get("from", {}).get("id")) != chat:
            _api("answerCallbackQuery", {"callback_query_id": cq["id"],
                                         "text": "Not allowed"})
            continue
        try:
            decision, post_id = cq.get("data", "").split(":", 1)
        except ValueError:
            continue
        decisions.append((decision, post_id))
        label = "✅ Approved — queued for the next slot" if decision == "ok" else "❌ Rejected"
        _api("answerCallbackQuery", {"callback_query_id": cq["id"], "text": label})
        msg = cq.get("message") or {}
        if msg:
            _api("editMessageReplyMarkup", {
                "chat_id": msg["chat"]["id"], "message_id": msg["message_id"],
                "reply_markup": json.dumps({"inline_keyboard": [[
                    {"text": label, "callback_data": "noop:x"}]]})})
    return decisions, offset
