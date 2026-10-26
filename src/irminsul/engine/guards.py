"""Input guards that run before any retrieval or LLM call.

Refusing deterministically here is safer (no model can be talked out of it) and free
(no tokens spent). Three kinds:
- prompt injection: attempts to override instructions or extract the system prompt
- leaks: datamines, betas, leak sites, or versions beyond the officially announced one
- off-topic: nothing in the question relates to Genshin Impact
"""

import re
from dataclasses import dataclass

from irminsul.engine.entities import EntityStore
from irminsul.engine.exact import is_patch_question
from irminsul.engine.types import Answer

MAX_CHARS = 600

_INJECTION = re.compile(
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)"
    r"|(system|developer) prompt|\byou are now\b|\bDAN\b|\bjailbreak|developer mode"
    r"|^\s*system\s*:|\b(disable|turn off|bypass)\w* (the |your )?(leak |safety )?(filter|rules)"
    r"|filter (is )?disabled|pretend (that )?you",
    re.I | re.M,
)
_LEAK = re.compile(
    r"\bleak(s|ed|er|ers)?\b|\bdatamin(e|ed|es|ing|ers?)\b|\bbeta\b|\bhakush|\bhomdgcat"
    r"|\bproject amber\b|\bunreleased\b",
    re.I,
)
_VERSION = re.compile(r"\b(?:version |v|patch )?([4-9])\.(\d)\b", re.I)
OTHER_GAMES = re.compile(
    r"honkai|star ?rail|\bhsr\b|zenless|\bzzz\b|wuthering|\bwuwa\b|valorant|league of legends"
    r"|fortnite|minecraft|pok[eé]mon|arknights|blue archive",
    re.I,
)
GENSHIN_TERMS = re.compile(
    r"genshin|teyvat|hoyo|mihoyo|paimon|traveler|archon|vision|primo|wish|banner|pity|resin"
    r"|artifact|weapon|talent|constellation|ascen|abyss|theater|domain|boss|build|team"
    r"|rotation|dps|support|healer|shield|reaction|vaporize|melt|freeze|bloom|swirl|conduct"
    r"|quicken|spread|aggravate|burgeon|stellar|anemo|geo|electro|dendro|hydro|pyro|cryo"
    r"|mondstadt|liyue|inazuma|sumeru|fontaine|natlan|snezhnaya|nod-krai|elemental|burst|skill"
    r"|energy recharge|\ber\b|crit|\bem\b|f2p|c[0-6]\b|r[1-5]\b|adventure rank|\bar\b|quest"
    r"|commission|map|pin|fate|starglitter|stardust|co-op|game",
    re.I,
)

LEAK_REPLY = (
    "I only answer from **officially released** information, so I can't help with leaks, "
    "datamines, beta details or unannounced content. Once HoYoverse officially reveals it, "
    "I'll have it, with sources."
)
INJECTION_REPLY = (
    "I can't change how I work or share my instructions. Ask me anything about Genshin "
    "Impact and I'll answer from official, released information, with sources."
)
OFFTOPIC_REPLY = (
    "I can only help with **Genshin Impact**: characters, builds, teams, mechanics, wishes and "
    "the story. Ask me something about Teyvat!"
)
TOO_LONG_REPLY = f"Please keep questions under {MAX_CHARS} characters."


@dataclass
class GuardConfig:
    live_version: tuple[int, int] = (7, 1)  # from the corpus manifest
    announced_version: tuple[int, int] = (7, 2)  # officially revealed, not yet live


def check(question: str, store: EntityStore | None, cfg: GuardConfig) -> Answer | None:
    """Return a refusal Answer, or None if the question may proceed."""
    if len(question) > MAX_CHARS:
        return Answer(TOO_LONG_REPLY, "refuse_length", trace={"guard": "length"})
    if _INJECTION.search(question):
        return Answer(INJECTION_REPLY, "refuse_injection", trace={"guard": "injection"})
    if _LEAK.search(question):
        return Answer(LEAK_REPLY, "refuse_leak", trace={"guard": "leak_terms"})
    future = [
        v for v in _VERSION.findall(question) if (int(v[0]), int(v[1])) > cfg.announced_version
    ]
    if future:
        return Answer(
            LEAK_REPLY,
            "refuse_leak",
            trace={"guard": "future_version", "versions": [".".join(v) for v in future]},
        )
    named = store.find(question) if store else []
    other_game = OTHER_GAMES.search(question) and not re.search(r"genshin", question, re.I)
    on_topic = named or GENSHIN_TERMS.search(question) or is_patch_question(question)
    if other_game or not on_topic:
        return Answer(OFFTOPIC_REPLY, "refuse_offtopic", trace={"guard": "offtopic"})
    return None


def version_from_manifest(game_version: str | None) -> tuple[int, int] | None:
    """Yatta reports e.g. '71F2' for 7.1."""
    if game_version and len(game_version) >= 2 and game_version[:2].isdigit():
        return int(game_version[0]), int(game_version[1])
    return None
