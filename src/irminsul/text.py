"""Cleanup of in-game rich text into plain Markdown-friendly text."""

import re

_COLOR = re.compile(r"</?color(=[^>]*)?>", re.IGNORECASE)
_ITALIC = re.compile(r"</?i>", re.IGNORECASE)
_LINK = re.compile(r"\{/?LINK(#[^}]*)?\}")
# Platform variants, e.g. {LAYOUT_MOBILE#Tap}{LAYOUT_PC#Press}{LAYOUT_PS#Press}: keep PC.
_LAYOUT = re.compile(r"\{LAYOUT_(MOBILE|PC|PS)#([^}]*)\}")
# Gendered variants, e.g. {F#she}{M#he}: keep the first form only.
_GENDER = re.compile(r"\{(F|M)#([^}]*)\}\{(F|M)#[^}]*\}")
_NICKNAME = re.compile(r"\{NICKNAME\}")
_PARAM = re.compile(r"\{param(\d+):([A-Z0-9]+)\}")


def clean(text: str | None) -> str:
    """Strip game markup tags and normalise line breaks."""
    if not text:
        return ""
    text = text.replace("\\n", "\n")
    text = _COLOR.sub("", text)
    text = _ITALIC.sub("", text)
    text = _LINK.sub("", text)
    text = _LAYOUT.sub(lambda m: m.group(2) if m.group(1) == "PC" else "", text)
    text = _GENDER.sub(lambda m: m.group(2), text)
    text = _NICKNAME.sub("Traveler", text)
    text = text.lstrip("#")  # some strings mark "formatted text" with a leading '#'
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def format_param(value: float, fmt: str) -> str:
    """Render one talent parameter using the game's format code.

    Codes: P = percent, F<n> = n decimals, I = integer; they combine (F1P = 12.3%).
    """
    if fmt == "I":
        return str(round(value))
    decimals = 0
    if m := re.search(r"F(\d)", fmt):
        decimals = int(m.group(1))
    if "P" in fmt:
        return f"{value * 100:.{decimals}f}%"
    return f"{value:.{decimals}f}"


def fill_params(template: str, params: list[float]) -> str:
    """Replace {paramN:FMT} placeholders with formatted values (N is 1-based)."""

    def sub(m: re.Match[str]) -> str:
        idx = int(m.group(1)) - 1
        if idx >= len(params):
            return "?"
        return format_param(params[idx], m.group(2))

    return _PARAM.sub(sub, template)
