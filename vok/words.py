"""Disguise words that Instagram/Facebook may limit reach for (VOK style).

Applied by code to every headline and caption, so it never depends on the AI
remembering. Edit the list below to add or change words.
"""

from __future__ import annotations

import re

# word stem  →  disguised stem   (endings like -ed, -s, -ing, -er are kept)
SWAPS = {
    "kill": "k!ll",
    "death": "de@th",
    "dead": "de@d",
    "die": "d!e",
    "died": "d!ed",
    "dying": "dy!ng",
    "murder": "m*rder",
    "suicide": "su!cide",
    "sex": "s*x",
    "rape": "r@pe",
    "porn": "p*rn",
    "nude": "n*de",
    "naked": "n@ked",
    "massacre": "m@ssacre",
    "genocide": "gen0cide",
    "behead": "beh3ad",
    "corpse": "c*rpse",
    "bodies": "b0dies",
    "drug": "dr*g",
    "terror": "terr0r",
    "slaughter": "sl@ughter",
    "abuse": "ab*se",
    "assault": "ass@ult",
    "torture": "t0rture",
}

# don't touch these normal words that start with a listed stem
KEEP = {"skill", "skills", "killer app", "dieting", "diet", "diesel", "sextet", "sexton",
        "essex", "middlesex", "sussex", "terrain", "terrace", "deadline", "deadlines",
        "deadlock", "deadlocked", "drugstore"}

_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(map(re.escape, SWAPS), key=len, reverse=True)) + r")([a-z]*)\b",
    re.IGNORECASE)

ENDINGS = {"", "s", "es", "ed", "d", "ing", "er", "ers", "ings", "ual", "ually", "y"}


def _match_case(src: str, out: str) -> str:
    if src.isupper():
        return out.upper()
    if src[:1].isupper():
        return out[:1].upper() + out[1:]
    return out


def disguise(text: str) -> str:
    def repl(m: re.Match) -> str:
        stem, ending = m.group(1), m.group(2)
        whole = (stem + ending).lower()
        if whole in KEEP or ending.lower() not in ENDINGS:
            return m.group(0)
        return _match_case(stem, SWAPS[stem.lower()]) + ending
    # leave hashtags and links alone
    parts = re.split(r"(#\w+|https?://\S+)", text)
    return "".join(p if p.startswith(("#", "http")) else _PATTERN.sub(repl, p) for p in parts)


if __name__ == "__main__":
    for t in ["5 terrorists KILLED in raid", "Death toll rises as dozens killed",
              "Sexual abuse claims rock ministry", "He died after being tortured",
              "Skills deadline missed", "Israeli strike kills 12", "#Vok #KilledInAction"]:
        print(f"{t!r:45} → {disguise(t)!r}")


# ---------------------------------------------------------------- no dashes

def no_dashes(text: str) -> str:
    """VOK style: no em/en dashes or hyphens anywhere in headline or caption.

    "Talks collapse — EU walks out"  → "Talks collapse, EU walks out"
    "US-Iran talks", "pro-Israel"    → "US Iran talks", "pro Israel"
    "2025-26", "7-year"              → "2025 to 26", "7 year"
    Hashtags and links are left alone.
    """
    def fix(part: str) -> str:
        part = re.sub(r"(^|\n)[ \t]*[-—–][ \t]+", r"\1", part)     # list bullets
        part = re.sub(r"[ \t]*[—–][ \t]*", ", ", part)             # em/en dash between clauses
        part = re.sub(r"(\d)\s*-\s*(\d{2,4})\b", r"\1 to \2", part)  # number ranges
        part = re.sub(r"(?<=\w)-(?=\w)", " ", part)              # hyphenated words
        part = re.sub(r"(?<=[A-Za-z])_(?=[A-Za-z])", " ", part)  # al_Helo → al Helo
        part = re.sub(r"[ \t]+-[ \t]+", ", ", part)               # spaced hyphen used as dash
        part = re.sub(r",\s*,", ",", part)
        part = re.sub(r"\s+,", ",", part)
        part = re.sub(r",\s*([.!?:])", r"\1", part)
        return re.sub(r"[ \t]{2,}", " ", part)
    parts = re.split(r"(#\w+|https?://\S+)", text)
    return "".join(p if p.startswith(("#", "http")) else fix(p) for p in parts)


AI_NOTE = "Note: AI image used for illustration purposes."
CTA = "Follow Vok for more stories like this."


def add_ai_note(caption: str) -> str:
    """Put the AI-image disclaimer right after the CTA line (before hashtags)."""
    if AI_NOTE in caption:
        return caption
    if CTA in caption:
        return caption.replace(CTA, f"{CTA}\n\n{AI_NOTE}", 1)
    return caption.rstrip() + f"\n\n{AI_NOTE}"


def clean(text: str) -> str:
    """Everything VOK text goes through: no dashes, then disguise words."""
    return disguise(no_dashes(text))
