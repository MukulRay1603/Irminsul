"""Reaction guides: one doc per newer reaction, compiled from official kit and weapon text.

Newer reactions (Stellar, Lunar, Moonsign, ...) have no single official explainer: the game
defines them across many character talents and weapon passives ("converted into the
Lunar-Charged reaction", "considered Stellar-Conduct DMG"). Searching 30 fragments rarely
surfaces the defining ones, so this gathers every official sentence about a reaction into one
guide, grouped by what it says and credited line by line. Nothing is written by a model, and
only released, official docs are used, so the leak gate's decisions carry over.
"""

import re
from collections import defaultdict
from datetime import datetime

from irminsul.schema import Doc, Release, ReleaseStatus, SourceRef, Tier, slugify

REACTIONS = (
    "Stellar-Conduct",
    "Stellar Swirl",
    "Lunar-Charged",
    "Lunar-Bloom",
    "Lunar-Crystallize",
    "Moonsign",
    "Nightsoul",
    "Hexerei",
)
SECTIONS = (
    ("convert", "What turns into it"),
    ("unlock", "Who can use it (states and fields that enable it)"),
    ("deals", "Who deals it (DMG that counts as this reaction)"),
    ("boosts", "What makes it stronger"),
    ("other", "Other official mentions"),
)
MAX_PER_SECTION = 25
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")


def _kind(sentence: str, reaction: str) -> str:
    r = re.escape(reaction)
    conversion = (
        rf"(convert\w*\s+(it\s+)?into|becomes?|turns?\s+into)\s+(an?\s+|the\s+)?[\w\s,-]*{r}"
    )
    if re.search(conversion, sentence, re.I):
        return "convert"
    if re.search(
        r"\b(when|while|after) .{0,60}(in the party|party's|state|field)", sentence, re.I
    ) and re.search(r"\bwill (enter|be|gain)\b", sentence, re.I):
        return "unlock"
    if re.search(rf"considered (as )?{r}( reaction)? DMG|{r}( reaction)? DMG that", sentence, re.I):
        return "deals"
    if re.search(r"increase|bonus|enhanc|boost|\bby \d", sentence, re.I):
        return "boosts"
    return "other"


def _who(doc: Doc) -> str:
    """'Ineffa: Moonsign Benediction' -> 'Ineffa', 'Beyond the Chrysalis' -> itself."""
    return doc.title.split(":")[0].replace(" constellations", "").replace(" overview", "").strip()


def reaction_guides(docs: list[Doc], now: datetime) -> list[Doc]:
    official = [
        d
        for d in docs
        if d.source.tier == Tier.OFFICIAL
        and d.release.status == ReleaseStatus.RELEASED
        and d.doc_id.startswith(("character/", "weapon/"))
    ]
    guides = []
    for reaction in REACTIONS:
        pattern = re.compile(re.escape(reaction), re.I)
        found: dict[str, list[str]] = defaultdict(list)
        urls: list[str] = []
        seen: set[str] = set()
        for doc in official:
            for raw in _SENTENCES.split(doc.text):
                sentence = " ".join(raw.split()).lstrip("•-|# ").strip()
                if not pattern.search(sentence) or sentence.startswith("|") or len(sentence) < 25:
                    continue
                key = sentence.lower()
                if key in seen:  # refinements and repeated passives repeat whole sentences
                    continue
                seen.add(key)
                section = _kind(sentence, reaction)
                if len(found[section]) < MAX_PER_SECTION:
                    found[section].append(f"- {_who(doc)}: {sentence}")
                    if doc.source.url not in urls:
                        urls.append(doc.source.url)
        if not found:
            continue
        lines = [
            f"# {reaction} (reaction guide)",
            f"{reaction} appears in the official descriptions of released characters and "
            "weapons. These are those descriptions, quoted and grouped by what they say.",
        ]
        for key, heading in SECTIONS:
            if found.get(key):
                lines += ["", f"## {heading}", *found[key]]
        guides.append(
            Doc(
                doc_id=f"mechanic/{slugify(reaction)}#guide",
                entity_id=None,
                kind="reaction_guide",
                title=f"{reaction}: reaction guide",
                text="\n".join(lines),
                release=Release(status=ReleaseStatus.RELEASED),
                source=SourceRef(
                    source="official-kits",
                    url=urls[0],
                    tier=Tier.OFFICIAL,
                    fetched_at=now,
                    refs=urls[:50],
                ),
            )
        )
    return guides
