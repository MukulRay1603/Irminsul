"""Guards: deterministic checks around the model, free to run and impossible to talk out of.

Input guards run before any retrieval or model call, in this order:
- length
- privacy: personal data in the question (emails, phone or ID numbers, passwords, street
  addresses) or a request for someone's private details. These are never cached.
- self-harm: a short supportive reply pointing to real help, not a game answer
- adult: sexual or explicit content
- cheats: hacks, mods, private servers, account trading, currency generators (HoYoverse ToS)
- prompt injection: attempts to override instructions or extract the system prompt
- leaks: datamines, betas, leak sites, or versions beyond the officially announced one
- off-topic: anything that isn't about Genshin Impact
The output guard (`check_output`) runs on what a model writes: it drops links that aren't
the cited official sources, redacts personal data, and blocks explicit content.
"""

import re
from dataclasses import dataclass

from irminsul.engine.entities import EntityStore
from irminsul.engine.exact import is_patch_question
from irminsul.engine.types import Answer

MAX_CHARS = 600

# ---------------------------------------------------------------- privacy
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# 9+ digits, optionally split by spaces, dashes or brackets (phone, card, account or UID
# numbers). Commas and dots don't count as separators, so "1,000,000 DMG" is fine.
_LONG_NUMBER = re.compile(r"(?<!\w)(?<!\d[.,])\+?\d(?:[ \-()]*\d){8,}(?!\w|[.,]\d)")
_SECRET = re.compile(
    r"\b(my )?(password|passcode|pin code|2fa|otp|verification code|login code|security code)"
    r"\b\s*(is|=|:)",
    re.I,
)
_ADDRESS = re.compile(
    r"\b\d{1,5}\s+[a-z]+(\s[a-z]+)?\s+(street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive)\b",
    re.I,
)
_MY_DETAILS = re.compile(
    r"\bmy (real |full |home )?(name|address|phone( number)?|number|email|e-mail|birthday|age)"
    r"\s+is\b",
    re.I,
)
_SEEK_OTHERS = re.compile(
    r"\bdox+(ing|x)?\b|\bhome address\b|\bip address of\b|\bphone number of\b"
    r"|\bwhere (does|do) .{1,40} live\b|\bpersonal (info|information|details) (of|about|on)\b",
    re.I,
)

# ---------------------------------------------------------------- wellbeing and content
_SELF_HARM = re.compile(
    r"\b(kill(ing)? myself|suicid(e|al)|self[- ]?harm|end (it all|my life)|want to die"
    r"|don'?t want to (live|be alive)|hurt(ing)? myself)\b",
    re.I,
)
_ADULT = re.compile(
    r"\b(nsfw|porn\w*|hentai|r-?34|rule ?34|nudes?|nudity|naked|sex|sexy|sexual\w*|erotic\w*"
    r"|lewd\w*|fetish\w*|onlyfans|boobs?|breasts?|horny|stripper|striptease|lingerie|kinky?"
    r"|xxx|18\+)(?![\w+])",
    re.I,
)
_CHEATS = re.compile(
    r"\b(cheat(s|ing)?|cheat engine|hack(s|ed|ing)?|hacker|mod ?menu|3dmigoto|gimi"
    r"|private servers?|grasscutter|aimbot|botting|auto[- ]?farm(ing)? (script|bot)s?"
    r"|speed ?hack|unlock fps|fps unlock(er)?|primo(gem)?s? (generator|hack)"
    r"|account (selling|buying|trading|for sale)|(buy|sell)(ing)? (an? |my )?(\w+ )?accounts?"
    r"|exploits?|glitch(es)? for (free )?primo(gem)?s)\b",
    re.I,
)

# ---------------------------------------------------------------- injection and leaks
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

# ---------------------------------------------------------------- topic
OTHER_GAMES = re.compile(
    r"honkai|star ?rail|\bhsr\b|zenless|\bzzz\b|wuthering|\bwuwa\b|valorant|league of legends"
    r"|fortnite|minecraft|pok[eé]mon|arknights|blue archive",
    re.I,
)
# Words that only make sense in Genshin: one is enough.
GENSHIN_STRONG = re.compile(
    r"genshin|teyvat|hoyo|mihoyo|paimon|travell?er|archons?|visions?|gnosis|primo\w*|resin"
    r"|constellations?|ascen\w*|abyss|imaginarium|stygian|anemo|geo|electro|dendro|hydro|pyro"
    r"|cryo|mondstadt|liyue|inazuma|sumeru|fontaine|natlan|snezhnaya|nod-?krai|khaenri"
    r"|vaporize|melt|swirl|superconduct|electro-charged|overload\w*|crystallize|quicken"
    r"|aggravate|hyperbloom|burgeon|bloom|stellar|lunar|moonsign|nightsoul|hexerei"
    r"|starglitter|stardust|intertwined|acquaint|fates?\b|adventure rank|commissions?"
    r"|talent books?|weekly boss|teapot|serenitea|genius invokation|\btcg\b|wish(es)?\b"
    r"|banners?|pity|[45][- ]?stars?|\bc[0-6]\b|\br[1-5]\b|redeem|redemption code"
    r"|livestream|dmg\b|damage (formula|calculation)|elemental"
    r"|selectors?|crystalfl\w*|ocul(?:i|us)|spiral abyss|free (?:5|4|five|four)[- ]?star",
    re.I,
)
# Common words that suggest Genshin only when nothing says otherwise.
GENSHIN_WEAK = re.compile(
    r"artifacts?|weapons?|talents?|builds?|teams?|rotations?|\bdps\b|support|healer|shield\w*"
    r"|reactions?|crit|energy recharge|\ber\b|\bem\b|elemental mastery|f2p|co-op|boss\w*"
    r"|domains?|quests?|map|skill|burst|game|meta|tier list|characters?|lore|story|damage"
    r"|pulls?|pulling|free pick|new account|events?|exploration|floor 1[0-2]",
    re.I,
)
# Clear signs a question is about something else entirely.
OFFTOPIC_SIGNS = re.compile(
    r"website|\bhtml\b|\bcss\b|javascript|python|\bjava\b|c\+\+|\bcode\b|coding|programm\w*"
    r"|\bsql\b|excel|essay|homework|assignment|\bmath\b|equation|calculus|physics|chemistry"
    r"|politic\w*|election|president|prime minister|religio\w*|medical|doctor|diagnos\w*"
    r"|symptoms?|medicine|disease|lawyer|legal advice|stocks?\b|crypto|bitcoin|invest\w*"
    r"|loan|mortgage|tax(es)?\b|weather|\bnews\b|celebrit\w*|dating|girlfriend|boyfriend"
    r"|relationship advice|resume|cv\b|job interview|translate (this|the following)",
    re.I,
)

# ---------------------------------------------------------------- replies
PRIVACY_REPLY = (
    "Please don't share personal details here: emails, phone or account numbers, passwords, "
    "addresses or your UID. I don't need them, and I won't help find anyone's private "
    "information. Ask me anything about Genshin Impact instead!"
)
SELF_HARM_REPLY = (
    "I'm really sorry you're going through this. I'm only a Genshin assistant, so I can't "
    "help the way a person can, but you don't have to deal with it alone. Please reach out to "
    "someone you trust, or a free, confidential support line: in the US you can call or text "
    "**988**, in the UK and Ireland call Samaritans on **116 123**, and "
    "**findahelpline.com** lists services in other countries. If you're in immediate danger, "
    "contact your local emergency number."
)
ADULT_REPLY = (
    "I keep things family-friendly, so I can't help with that. Ask me about characters, "
    "builds, teams, mechanics or the story!"
)
CHEATS_REPLY = (
    "I can't help with cheats, mods, private servers, exploits or account trading: they "
    "break HoYoverse's Terms of Service and can get accounts banned. I'm happy to help you "
    "get stronger the legit way!"
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
BLOCKED_OUTPUT_REPLY = (
    "I couldn't give a safe answer to that one. Try asking about characters, builds, teams "
    "or mechanics!"
)
# Routes whose question text must never be kept in memory (cache, logs)
SENSITIVE_ROUTES = ("refuse_privacy", "refuse_selfharm")


@dataclass
class GuardConfig:
    live_version: tuple[int, int] = (7, 1)  # from the corpus manifest
    announced_version: tuple[int, int] = (7, 2)  # officially revealed, not yet live


def _refuse(text: str, route: str, guard: str, **extra) -> Answer:
    return Answer(text, route, trace={"guard": guard, **extra})


def has_personal_data(text: str) -> bool:
    return bool(
        _EMAIL.search(text)
        or _LONG_NUMBER.search(text)
        or _SECRET.search(text)
        or _ADDRESS.search(text)
        or _MY_DETAILS.search(text)
    )


def check(question: str, store: EntityStore | None, cfg: GuardConfig) -> Answer | None:
    """Return a refusal Answer, or None if the question may proceed."""
    if len(question) > MAX_CHARS:
        return _refuse(TOO_LONG_REPLY, "refuse_length", "length")
    named = store.find(question) if store else []
    if has_personal_data(question) or (_SEEK_OTHERS.search(question) and not named):
        return _refuse(PRIVACY_REPLY, "refuse_privacy", "privacy")
    if _SELF_HARM.search(question):
        return _refuse(SELF_HARM_REPLY, "refuse_selfharm", "self_harm")
    if _ADULT.search(question):
        return _refuse(ADULT_REPLY, "refuse_adult", "adult")
    if _CHEATS.search(question):
        return _refuse(CHEATS_REPLY, "refuse_cheats", "cheats")
    if _INJECTION.search(question):
        return _refuse(INJECTION_REPLY, "refuse_injection", "injection")
    if _LEAK.search(question):
        return _refuse(LEAK_REPLY, "refuse_leak", "leak_terms")
    future = [
        v for v in _VERSION.findall(question) if (int(v[0]), int(v[1])) > cfg.announced_version
    ]
    if future:
        return _refuse(
            LEAK_REPLY, "refuse_leak", "future_version", versions=[".".join(v) for v in future]
        )
    # "What changed in 7.1?" names no character but is plainly about the game
    if not (on_topic(question, bool(named)) or is_patch_question(question)):
        return _refuse(OFFTOPIC_REPLY, "refuse_offtopic", "offtopic")
    return None


def on_topic(question: str, names_an_entity: bool) -> bool:
    """Genshin unless it names another game, or shows clear signs of another subject."""
    strong = bool(GENSHIN_STRONG.search(question)) or names_an_entity
    if OTHER_GAMES.search(question) and not re.search(r"genshin", question, re.I):
        return False
    if OFFTOPIC_SIGNS.search(question) and not strong:
        return False
    return strong or bool(GENSHIN_WEAK.search(question))


_URL = re.compile(r"https?://[^\s)\]>]+|www\.[^\s)\]>]+")


def check_output(text: str, allowed_urls: list[str]) -> tuple[str, list[str]]:
    """Clean a model's answer: only cited official links, no personal data, nothing explicit."""
    flags: list[str] = []
    if _ADULT.search(text):
        return BLOCKED_OUTPUT_REPLY, ["adult"]
    allowed = tuple(u.rstrip("/") for u in allowed_urls if u.startswith("http"))

    def link(m: re.Match) -> str:
        url = m.group(0).rstrip(".,;:")
        if allowed and url.rstrip("/").startswith(allowed):
            return m.group(0)
        flags.append("link")
        return "(link removed)"

    text = _URL.sub(link, text)
    text, emails = _EMAIL.subn("(email removed)", text)
    text, numbers = _LONG_NUMBER.subn("(number removed)", text)
    if emails or numbers:
        flags.append("personal_data")
    return text, flags


def version_from_manifest(game_version: str | None) -> tuple[int, int] | None:
    """Yatta reports e.g. '71F2' for 7.1."""
    if game_version and len(game_version) >= 2 and game_version[:2].isdigit():
        return int(game_version[0]), int(game_version[1])
    return None
