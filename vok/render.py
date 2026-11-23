"""VOK post renderer.

Builds a 1080x1350 news post in the VOK house style:
- full-bleed photo, smart-cropped so the subject sits in the top part
- dark navy gradient at the bottom
- white NEWS/VIRAL tag, balanced all-caps headline, READ CAPTION pill
- VOK logo top-left

Usage:
    python -m vok.render --image photo.jpg --headline "Some headline" --out post.jpg
"""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
LOGO = ROOT / "assets" / "logo.png"

W, H = 1080, 1350
NAVY = (5, 38, 49)          # #052631, from the Canva template
WHITE = (255, 255, 255)

MARGIN_X = 40               # left edge of tag + headline
HEADLINE_MAX_W = W - 2 * MARGIN_X
HEADLINE_BOTTOM = 1192      # headline block always ends here
TEXT_ZONE_TOP = 760         # nothing important in the photo below this line
FOCUS_Y = 0.36              # where the photo's subject lands (fraction of height)


def font(weight: int, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"poppins-latin-{weight}-normal.woff"), size)


# ---------------------------------------------------------------- photo crop

CASCADE = ROOT / "assets" / "haarcascade_frontalface_default.xml"


def _subject(img: Image.Image) -> tuple[float, float]:
    """Return the subject's position (x, y as 0..1) in the source photo.

    Faces win if any are found; otherwise we use the centre of visual detail
    (edges), which usually lands on the building / ship / fire, not the sky.
    """
    try:
        import cv2
        import numpy as np

        arr = np.array(img.convert("L"))
        cascade = cv2.CascadeClassifier(str(CASCADE))
        faces = cascade.detectMultiScale(arr, scaleFactor=1.1, minNeighbors=6,
                                         minSize=(arr.shape[1] // 20,) * 2)
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            # aim a bit below the face centre so the head isn't cut at the top
            return (x + w / 2) / arr.shape[1], (y + h * 0.8) / arr.shape[0]

        edges = cv2.Canny(arr, 80, 200).astype(float)
        if edges.sum() > 0:
            ys, xs = np.arange(edges.shape[0]), np.arange(edges.shape[1])
            cy = (edges.sum(axis=1) * ys).sum() / edges.sum() / edges.shape[0]
            cx = (edges.sum(axis=0) * xs).sum() / edges.sum() / edges.shape[1]
            return float(cx), float(cy)
    except Exception:
        pass
    return 0.5, 0.45


def smart_crop(img: Image.Image, focus: tuple[float, float] | None = None) -> Image.Image:
    """Cover-scale to 1080x1350, keep the subject in frame and above the text."""
    img = img.convert("RGB")
    sx, sy = _subject(img) if focus is None else focus
    scale = max(W / img.width, H / img.height)
    nw, nh = round(img.width * scale), round(img.height * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = max(0, min(round(sx * nw - W / 2), nw - W))
    top = max(0, min(round(sy * nh - FOCUS_Y * H), nh - H))
    return img.crop((left, top, left + W, top + H))


# ---------------------------------------------------------------- headline

def _balanced_lines(words: list[str], f: ImageFont.FreeTypeFont, max_w: int):
    """Split words into the fewest lines that fit, with line widths as equal
    as possible (so no line is much longer than the others)."""
    def width(s: str) -> int:
        return f.getbbox(s)[2]

    n = len(words)
    for n_lines in range(1, min(n, 6) + 1):
        best, best_score = None, None
        for cuts in itertools.combinations(range(1, n), n_lines - 1):
            bounds = (0, *cuts, n)
            lines = [" ".join(words[a:b]) for a, b in zip(bounds, bounds[1:])]
            widths = [width(l) for l in lines]
            if max(widths) > max_w:
                continue
            # prefer equal lines; small penalty if the last line is the longest
            score = max(widths) - min(widths)
            if widths[-1] > widths[0]:
                score += 20
            if best_score is None or score < best_score:
                best, best_score = lines, score
        if best:
            return best
    return None


def fit_headline(text: str):
    words = text.upper().split()
    # keep dashes on the end of the previous line, never at the start of one
    merged: list[str] = []
    for w in words:
        if w in {"—", "–", "-"} and merged:
            merged[-1] += " " + w
        else:
            merged.append(w)
    words = merged
    for size in range(64, 47, -2):            # 64px like the template, shrink if long
        f = font(800, size)
        lines = _balanced_lines(words, f, HEADLINE_MAX_W)
        if lines and len(lines) <= 4:
            return f, lines
    f = font(800, 48)
    return f, _balanced_lines(words, f, HEADLINE_MAX_W) or [" ".join(words)]


# ---------------------------------------------------------------- drawing

def _gradient(canvas: Image.Image):
    # smooth fade: transparent at y=520, ~95% navy at the bottom
    start = 520
    col = Image.new("L", (1, H), 0)
    for y in range(start, H):
        t = (y - start) / (H - start)
        s = t * t * (3 - 2 * t)                # smoothstep, no hard edge
        col.putpixel((0, y), int(242 * s))
    alpha = col.resize((W, H))
    grad = Image.new("RGBA", (W, H), (*NAVY, 0))
    grad.putalpha(alpha)
    canvas.alpha_composite(grad)

    # soft shade behind the logo so it reads on bright photos
    top = Image.new("L", (1, 240), 0)
    for y in range(240):
        top.putpixel((0, y), int(95 * (1 - y / 240) ** 1.6))
    shade = Image.new("RGBA", (W, 240), (0, 0, 0, 0))
    shade.putalpha(top.resize((W, 240)))
    canvas.alpha_composite(shade)


def _logo(canvas: Image.Image):
    if LOGO.exists():
        logo = Image.open(LOGO).convert("RGBA")
        logo.thumbnail((156, 68), Image.LANCZOS)
        canvas.alpha_composite(logo, (44, 40))
    else:  # placeholder until the real logo file is added
        d = ImageDraw.Draw(canvas)
        d.text((44, 36), "VOK", font=font(800, 56), fill=WHITE)


def _boxed_label(d: ImageDraw.ImageDraw, text: str, f, x: int, y: int,
                 pad_x: int, pad_y: int, center: bool = False):
    bx = f.getbbox(text)
    tw, th = bx[2] - bx[0], bx[3] - bx[1]
    bw, bh = tw + 2 * pad_x, th + 2 * pad_y
    if center:
        x = (W - bw) // 2
    d.rectangle((x, y, x + bw, y + bh), fill=WHITE)
    d.text((x + pad_x - bx[0], y + pad_y - bx[1]), text, font=f, fill=NAVY)
    return bh


def render(image_path: str, headline: str, out_path: str,
           label: str = "NEWS", focus: tuple[float, float] | None = None) -> str:
    photo = smart_crop(Image.open(image_path), focus)
    canvas = photo.convert("RGBA")
    _gradient(canvas)
    _logo(canvas)
    d = ImageDraw.Draw(canvas)

    hf, lines = fit_headline(headline)
    line_h = round(hf.size * 1.14)
    block_h = line_h * len(lines)
    y = HEADLINE_BOTTOM - block_h

    # tag sits just above the headline, left-aligned with it
    tag_f = font(800, 44)
    tag_h = tag_f.getbbox(label.upper())[3] - tag_f.getbbox(label.upper())[1] + 14
    _boxed_label(d, label.upper(), tag_f, MARGIN_X, y - tag_h - 14, 12, 7)

    for i, line in enumerate(lines):
        top = hf.getbbox(line)[1]
        d.text((MARGIN_X, y + i * line_h - top + (line_h - hf.size) // 2),
               line, font=hf, fill=WHITE)

    _boxed_label(d, "READ CAPTION", font(800, 28), 0, 1222, 10, 6, center=True)

    canvas.convert("RGB").save(out_path, "JPEG", quality=92)
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--headline", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="NEWS")
    ap.add_argument("--focus", type=float, nargs=2, metavar=("X", "Y"), default=None,
                    help="manual subject position, 0..1 each (overrides auto-detect)")
    a = ap.parse_args()
    print(render(a.image, a.headline, a.out, a.label,
                 tuple(a.focus) if a.focus else None))
