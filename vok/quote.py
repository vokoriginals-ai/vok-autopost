"""VOK quote post (1080x1350), rebuilt from VOK's Canva quote template:
black background, VOK logo top left, teal quote mark, white serif quote with the last
part highlighted in teal, name + title bottom left, the speaker cut out bottom right."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
W, H = 1080, 1350
BG = (10, 10, 10)
WHITE = (245, 245, 245)
TEAL = (107, 154, 155)
GREY_TEAL = (120, 145, 146)
MARGIN = 80

_session = None


def serif(weight: int, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / f"source-serif-4-latin-{weight}-normal.woff"), size)


def cutout(photo: str, cache: Path | None = None) -> Image.Image:
    """Person with the background removed (cached next to the photo)."""
    global _session
    if cache and cache.exists():
        return Image.open(cache).convert("RGBA")
    from rembg import new_session, remove
    if _session is None:
        _session = new_session("u2net_human_seg")
    out = remove(Image.open(photo).convert("RGB"), session=_session).convert("RGBA")
    bbox = out.getbbox()
    if bbox:
        out = out.crop(bbox)
    if cache:
        out.save(cache)
    return out


def _wrap(tokens: list[tuple[str, bool]], fonts: dict, width_at) -> list[list[tuple[str, bool]]]:
    """Greedy wrap of (word, highlighted) tokens; width_at(line_no) gives each line's room,
    so lines beside the speaker's photo are narrower."""
    lines, line, width = [], [], 0
    space = fonts[False].getlength(" ")
    for word, hl in tokens:
        w = fonts[hl].getlength(word)
        add = w if not line else space + w
        if line and width + add > width_at(len(lines)):
            lines.append(line)
            line, width = [(word, hl)], w
        else:
            line.append((word, hl))
            width += add
    if line:
        lines.append(line)
    return lines


def render_quote(quote: str, highlight: str, name: str, title: str, photo: str | None,
                 out_path: str, cache: Path | None = None) -> None:
    img = Image.new("RGB", (W, H), BG)

    # speaker, bottom right, fading into black at the left and top edges
    person_top, person_left = H, W
    if photo:
        person = cutout(photo, cache)
        target_h = 720
        person = person.resize((int(person.width * target_h / person.height), target_h), Image.LANCZOS)
        if person.width > 640:                       # very wide (two people): limit width
            person = person.resize((640, int(person.height * 640 / person.width)), Image.LANCZOS)
        alpha = person.getchannel("A")
        fade = Image.new("L", person.size, 255)
        fd = ImageDraw.Draw(fade)
        for x in range(min(120, person.width)):      # soft left edge
            fd.line([(x, 0), (x, person.height)], fill=int(255 * x / 120))
        alpha = Image.composite(alpha, Image.new("L", person.size, 0), fade)
        person.putalpha(alpha.filter(ImageFilter.GaussianBlur(1)))
        px, py = W - person.width + 20, H - person.height
        img.paste(person, (px, py), person)
        # where the person really starts (ignore the faded edge)
        box = person.getchannel("A").point(lambda a: 255 if a > 60 else 0).getbbox()
        if box:
            person_top, person_left = py + box[1], px + box[0]

    d = ImageDraw.Draw(img)

    # logo
    logo = Image.open(ASSETS / "logo.png").convert("RGBA")
    lw = 210
    logo = logo.resize((lw, int(logo.height * lw / logo.width)), Image.LANCZOS)
    img.paste(logo, (MARGIN, 70), logo)

    # quote mark
    d.text((MARGIN - 4, 150), "“", font=serif(700, 150), fill=TEAL)

    # quote text: largest size that fits the space above the name block
    quote = quote.strip().strip('"“”')
    highlight = highlight.strip().strip('"“”')
    if highlight and highlight in quote:
        head, tail = quote.rsplit(highlight, 1)
        tokens = [(w, False) for w in head.split()] + [(w, True) for w in highlight.split()] \
            + [(w, False) for w in tail.split()]
    else:
        tokens = [(w, False) for w in quote.split()]
    top, bottom = 300, 1060
    first = chosen = None
    for size in range(78, 30, -2):
        fonts = {False: serif(400, size), True: serif(700, size)}
        lh = int(size * 1.32)
        def room(i, lh=lh):
            line_bottom = top + (i + 1) * lh
            if line_bottom > person_top - 10:
                return max(360, person_left - MARGIN - 30)
            return 800
        lines = _wrap(tokens, fonts, room)
        if len(lines) * lh > bottom - top:
            continue
        first = first or (fonts, lh, lines)
        # avoid a thin column of 1 to 2 words beside the person: allow at most 2 narrow lines
        narrow = sum(1 for i in range(len(lines)) if top + (i + 1) * lh > person_top - 10)
        if narrow <= 2 or size <= 44:
            chosen = (fonts, lh, lines)
            break
    fonts, lh, lines = chosen or first
    y = top
    for line in lines:
        x = MARGIN
        for i, (word, hl) in enumerate(line):
            f = fonts[hl]
            d.text((x, y), word, font=f, fill=TEAL if hl else WHITE)
            x += f.getlength(word) + fonts[False].getlength(" ")
        y += lh

    # name and title, bottom left
    nf = serif(700, 44)
    tf = serif(400, 28)
    d.text((MARGIN, 1170), name, font=nf, fill=WHITE)
    d.text((MARGIN, 1228), title, font=tf, fill=GREY_TEAL)

    img.save(out_path, quality=95)
