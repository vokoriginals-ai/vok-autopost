"""Tiny HTTP helpers using only Python's standard library (no pip needed)."""

from __future__ import annotations

import json
import uuid
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 vok-autopost")


class HTTPError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:400]}")
        self.status, self.body = status, body


def _open(req: urllib.request.Request, timeout: int) -> bytes:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            if data[:2] == b"\x1f\x8b":          # some servers gzip even unasked
                import gzip
                data = gzip.decompress(data)
            return data
    except urllib.error.HTTPError as e:
        raise HTTPError(e.code, e.read().decode("utf-8", "replace")) from None


def get(url: str, params: dict | None = None, timeout: int = 30,
        headers: dict | None = None) -> bytes:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    return _open(req, timeout)


def get_json(url: str, params: dict | None = None, timeout: int = 30) -> dict:
    return json.loads(get(url, params, timeout))


def post_form(url: str, data: dict, timeout: int = 60) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
    return json.loads(_open(req, timeout))


def post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 90) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"User-Agent": UA, "Content-Type": "application/json", **(headers or {})})
    return json.loads(_open(req, timeout))


def post_multipart(url: str, fields: dict, files: dict, timeout: int = 120) -> dict:
    """files: {field_name: (filename, bytes, content_type)}"""
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'
                     .encode() + str(v).encode() + b"\r\n")
    for k, (fname, content, ctype) in files.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; '
                     f'filename="{fname}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()
                     + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        url, data=b"".join(parts),
        headers={"User-Agent": UA, "Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.loads(_open(req, timeout))
