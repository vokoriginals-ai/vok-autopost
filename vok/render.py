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
import re
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
PROFILE = ROOT / "assets" / "haarcascade_profileface.xml"


def _faces(img: Image.Image) -> list:
    """Confident faces in the photo (front or side)."""
    import cv2
    import numpy as np
    arr = np.array(img.convert("L"))
    small = (arr.shape[1] // 20,) * 2
    found = []
    for path, image, flip in ((CASCADE, arr, False), (PROFILE, arr, False),
                              (PROFILE, arr[:, ::-1].copy(), True)):
        if not path.exists():
            continue
        boxes, _, levels = cv2.CascadeClassifier(str(path)).detectMultiScale3(
            image, 1.1, 6, minSize=small, outputRejectLevels=True)
        found += [b for b, lv in zip(boxes, levels) if float(lv) > 1.0]
    return found


def _subject(img: Image.Image) -> tuple[float, float]:
    """Return the subject's position (x, y as 0..1) in the source photo.

    Faces win if any are found; otherwise we use the centre of visual detail
    (edges), which usually lands on the building / ship / fire, not the sky.
    """
    try:
        import cv2
        import numpy as np

        arr = np.array(img.convert("L"))
        small = (arr.shape[1] // 20,) * 2
        found = []                                  # (x, y, w, h, confidence)

        def scan(path, image, flip=False):
            c = cv2.CascadeClassifier(str(path))
            boxes, _, levels = c.detectMultiScale3(image, 1.1, 6, minSize=small,
                                                    outputRejectLevels=True)
            for (x, y, w, h), lv in zip(boxes, levels):
                if flip:
                    x = image.shape[1] - x - w
                found.append((x, y, w, h, float(lv)))

        scan(CASCADE, arr)
        if PROFILE.exists():                        # people turned sideways (both ways)
            scan(PROFILE, arr)
            scan(PROFILE, arr[:, ::-1].copy(), flip=True)
        if found:
            biggest = max(f[2] for f in found)
            # most certain face wins; size only breaks near-ties
            x, y, w, h, _ = max(found, key=lambda f: f[4] + 0.5 * f[2] / biggest)
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

WEAK_END = {"A", "AN", "THE", "OF", "TO", "IN", "ON", "AT", "AS", "FOR", "AND", "OR",
            "BY", "WITH", "FROM", "IS", "ITS", "HIS", "HER", "THEIR", "THAT", "WHO"}


def _ragged(widths: list[int]) -> float:
    """How uneven the lines look: 0 = all lines the same width.
    A short line in the middle (or a long last line) looks odd, so those cost more."""
    m = max(widths)
    score = sum(((m - w) / m) ** 2 for w in widths)
    for i, w in enumerate(widths[1:-1], 1):          # dip in the middle: zig-zag shape
        if w < widths[i - 1] and w < widths[i + 1]:
            score += 0.15
    if len(widths) > 1 and widths[-1] > widths[0] * 1.05:
        score += 0.05
    return score


def _balanced_lines(words: list[str], f: ImageFont.FreeTypeFont, max_w: int, n_lines: int):
    """Best split of words into exactly n_lines lines that fit, or None."""
    def width(s: str) -> int:
        return f.getbbox(s)[2]
    n = len(words)
    if n_lines > n:
        return None
    best, best_score = None, None
    for cuts in itertools.combinations(range(1, n), n_lines - 1):
        bounds = (0, *cuts, n)
        lines = [" ".join(words[a:b]) for a, b in zip(bounds, bounds[1:])]
        widths = [width(l) for l in lines]
        if max(widths) > max_w:
            continue
        sc = _ragged(widths)
        # a line ending on "A", "THE", "OF"... reads badly
        sc += 0.12 * sum(1 for l in lines[:-1] if l.split()[-1] in WEAK_END)
        if best_score is None or sc < best_score:
            best, best_score = lines, sc
    return (best, best_score) if best else None


def fit_headline(text: str):
    """Pick font size (64 down to 50) and 2 to 4 lines so the block looks even.
    Bigger text wins unless a slightly smaller size gives clearly straighter lines."""
    words = text.upper().split()
    merged: list[str] = []
    for w in words:                     # never start a line with a dash
        if w in {"—", "–", "-"} and merged:
            merged[-1] += " " + w
        else:
            merged.append(w)
    words = merged
    options = []
    for size in range(64, 49, -2):
        f = font(800, size)
        for n_lines in (1, 2, 3, 4):
            r = _balanced_lines(words, f, HEADLINE_MAX_W, n_lines)
            if not r:
                continue
            lines, rag = r
            # cost: uneven lines + smaller text + extra lines
            cost = rag * 1.0 + (64 - size) * 0.012 + (n_lines - 1) * 0.02
            if n_lines == 1 and len(words) > 3:
                cost += 0.3
            options.append((cost, size, lines))
    if options:
        _, size, lines = min(options, key=lambda o: o[0])
        return font(800, size), lines
    f = font(800, 48)
    return f, [" ".join(words)]


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


RED = (214, 32, 48)


def _boxed_label(d: ImageDraw.ImageDraw, text: str, f, x: int, y: int,
                 pad_x: int, pad_y: int, center: bool = False, bg=None, fg=None):
    bx = f.getbbox(text)
    tw, th = bx[2] - bx[0], bx[3] - bx[1]
    bw, bh = tw + 2 * pad_x, th + 2 * pad_y
    if center:
        x = (W - bw) // 2
    d.rectangle((x, y, x + bw, y + bh), fill=bg or WHITE)
    d.text((x + pad_x - bx[0], y + pad_y - bx[1]), text, font=f, fill=fg or NAVY)
    return bh


# ---------------- VIRAL templates ----------------
VIRAL_TEAL = (94, 214, 196)      # bright VOK teal, chosen by Saad
GAMING = re.compile(r"\b(gta|grand theft auto|rockstar|playstation|ps5|xbox|nintendo|switch 2|gamer|gamers|"
                    r"gaming|video game|esports|steam|fortnite|minecraft|call of duty|twitch|streamer|"
                    r"roblox|valorant|pubg|ea sports fc|elden ring)\b", re.I)


def is_gaming(text: str) -> bool:
    return bool(GAMING.search(text or ""))


def _hl_words(headline: str, highlight: str) -> list[tuple[str, bool]]:
    ws = headline.upper().split()
    hl = highlight.upper().split()
    mark = [False] * len(ws)
    if hl:
        n = len(hl)
        strip = lambda w: re.sub(r"[^\w!@*]", "", w)
        for i in range(len(ws) - n + 1):
            if [strip(w) for w in ws[i:i + n]] == [strip(w) for w in hl]:
                for j in range(i, i + n):
                    mark[j] = True
                break
    return list(zip(ws, mark))


def _wrap_hl(ws, f, max_w):
    lines, cur = [], []
    for w in ws:
        test = " ".join(x for x, _ in cur + [w])
        if cur and f.getlength(test) > max_w:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    lines.append(cur)
    return lines


def _fit_hl(ws, max_w, sizes, max_lines):
    for size in sizes:
        f = font(800, size)
        lines = _wrap_hl(ws, f, max_w)
        if len(lines) <= max_lines:
            return f, lines
    f = font(800, sizes[-1])
    return f, _wrap_hl(ws, f, max_w)


def _draw_hl(d, lines, f, x, y, lh, color):
    for line in lines:
        cx = x
        for w, hl in line:
            d.text((cx, y), w, font=f, fill=color if hl else WHITE)
            cx += f.getlength(w) + f.getlength(" ")
        y += lh
    return y


def _pill(d, x, y, text, f, bg, fg):
    b = f.getbbox(text)
    w, h = b[2] - b[0] + 44, b[3] - b[1] + 24
    d.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=bg)
    d.text((x + 22 - b[0], y + 12 - b[1]), text, font=f, fill=fg)
    return w, h


def render_viral_spotlight(image_path, headline, out_path, highlight="", focus=None):
    c = smart_crop(Image.open(image_path), focus).convert("RGBA")
    g = Image.new("RGBA", (W, H))
    gd = ImageDraw.Draw(g)
    for yy in range(H):
        t = max(0, (yy - 620) / (H - 620))
        gd.line((0, yy, W, yy), fill=(0, 0, 0, int(235 * min(1, t ** 1.2))))
    c.alpha_composite(g)
    _logo(c)
    d = ImageDraw.Draw(c)
    pf = font(800, 34)
    pw = pf.getbbox("VIRAL")[2] + 44
    _pill(d, W - 40 - pw, 44, "VIRAL", pf, VIRAL_TEAL, NAVY)
    f, lines = _fit_hl(_hl_words(headline, highlight), W - 80, (70, 64, 58, 52), 4)
    lh = round(f.size * 1.14)
    y = 1250 - len(lines) * lh
    _draw_hl(d, lines, f, 40, y, lh, VIRAL_TEAL)
    d.rectangle((40, 1272, 140, 1278), fill=VIRAL_TEAL)
    d.text((160, 1260), "READ CAPTION  \u2022  VOK ORIGINALS", font=font(600, 24), fill=(220, 220, 220))
    c.convert("RGB").save(out_path, "JPEG", quality=92)
    return out_path


def render_viral_glass(image_path, headline, out_path, highlight="", focus=None):
    from PIL import ImageFilter, ImageEnhance
    base = smart_crop(Image.open(image_path), focus).convert("RGBA")
    f, lines = _fit_hl(_hl_words(headline, highlight), W - 140, (60, 56, 52, 48), 4)
    lh = round(f.size * 1.2)
    text_h = len(lines) * lh
    top = H - 30 - (90 + 30 + text_h + 105)       # tag + gap + headline + footer
    box = (30, top, W - 30, H - 30)
    blur = base.crop(box).filter(ImageFilter.GaussianBlur(28))
    blur = ImageEnhance.Brightness(blur).enhance(0.55)
    mask = Image.new("L", blur.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, blur.width - 1, blur.height - 1), radius=40, fill=255)
    base.paste(blur, box[:2], mask)
    d = ImageDraw.Draw(base)
    d.rounded_rectangle(box, radius=40, outline=(255, 255, 255, 90), width=2)
    _logo(base)
    tag = Image.new("RGBA", (230, 58))
    td = ImageDraw.Draw(tag)
    a, b = (255, 61, 127), (140, 60, 255)
    for x in range(230):
        t = x / 229
        td.line((x, 0, x, 58), fill=tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3)))
    m = Image.new("L", tag.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, 229, 57), radius=29, fill=255)
    base.paste(tag, (70, top + 35), m)
    tf = font(800, 30)
    d.text((70 + (230 - tf.getlength("VIRAL")) / 2, top + 45), "VIRAL", font=tf, fill=WHITE)
    _draw_hl(d, lines, f, 70, top + 125, lh, VIRAL_TEAL)
    d.text((70, H - 85), "READ CAPTION", font=font(700, 24), fill=(230, 230, 230))
    pf = font(700, 22)
    pw = pf.getbbox("TRENDING")[2] + 44
    _pill(d, W - 70 - pw, H - 98, "TRENDING", pf, WHITE, NAVY)
    base.convert("RGB").save(out_path, "JPEG", quality=92)
    return out_path


def render(image_path: str, headline: str, out_path: str,
           label: str = "NEWS", focus: tuple[float, float] | None = None,
           highlight: str = "", gaming: bool | None = None) -> str:
    if label.upper() == "VIRAL":
        if gaming is None:
            gaming = is_gaming(headline)
        fn = render_viral_glass if gaming else render_viral_spotlight
        return fn(image_path, headline, out_path, highlight, focus)
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
    if label.upper() == "BREAKING":      # Saad's breaking template: red tag with a dot
        tag_f = font(700, 34)
        text = "\u2022  B R E A K I N G"
        tag_h = tag_f.getbbox(text)[3] - tag_f.getbbox(text)[1] + 20
        _boxed_label(d, text, tag_f, MARGIN_X, y - tag_h - 18, 16, 10, bg=RED, fg=WHITE)
    else:
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
