"""Exact sums inside answers: a model never does the arithmetic.

Damage formulas are KQM's, read from their Theorycrafting Library's formula files. Talent costs
and domain days are game data from the planner. Each answer shows its working, and a question
missing a number it needs goes on to the normal path instead of being guessed at.
"""

import re
from datetime import UTC, datetime, timedelta

from irminsul.engine.types import Answer, Citation

FORMULAS = "https://library.keqingmains.com/combat-mechanics/damage/damage-formula"
SCHEDULE = "https://gi.yatta.moe/en/archive/material"

# (name, multiplier, the EM bonus's numerator and offset)
_AMPLIFYING = (2.78, 1400)
_TRANSFORMATIVE = (16, 2000)
_ADDITIVE = (5, 1200)
REACTIONS = {
    "vaporize": _AMPLIFYING,
    "vape": _AMPLIFYING,
    "melt": _AMPLIFYING,
    "overload": _TRANSFORMATIVE,
    "overloaded": _TRANSFORMATIVE,
    "electro-charged": _TRANSFORMATIVE,
    "superconduct": _TRANSFORMATIVE,
    "swirl": _TRANSFORMATIVE,
    "shattered": _TRANSFORMATIVE,
    "bloom": _TRANSFORMATIVE,
    "hyperbloom": _TRANSFORMATIVE,
    "burgeon": _TRANSFORMATIVE,
    "burning": _TRANSFORMATIVE,
    "aggravate": _ADDITIVE,
    "spread": _ADDITIVE,
}
_REACTION = re.compile(r"\b(" + "|".join(REACTIONS) + r")\b", re.I)
_EM = re.compile(
    r"\b(\d{1,4})\s*(?:em\b|elemental mastery\b)|\b(?:em|elemental mastery)\D{0,12}(\d{1,4})\b",
    re.I,
)
_LEVELS = re.compile(r"\b(?:lv\.?|level)\s*(\d{1,3})\b.*?\b(?:lv\.?|level)\s*(\d{1,3})\b", re.I)
_DEF_ASK = re.compile(r"\bdef(?:ense|ence)?\b.{0,24}\b(?:mult\w*|shred|reduction|ignore)\b", re.I)
_DEF_CUT = re.compile(r"(\d{1,3})\s*%\s*(?:def(?:ense|ence)?\s*)?(?:shred|reduction)", re.I)
_RES_ASK = re.compile(
    r"\bres(?:istance)?\b.{0,24}\bmult\w*|\bdamage\b.{0,30}\bres(?:istance)?\b", re.I
)
_RES = re.compile(r"(-?\d{1,3})\s*%\s*(?:\w+\s+)?res(?:istance)?\b", re.I)
_RES_CUT = re.compile(r"(\d{1,3})\s*%\s*(?:res(?:istance)?\s*)?(?:shred|reduction)", re.I)
_TALENT = re.compile(
    r"\b(?:books?|materials?|crowns?|cost)\b.*\btalents?\b|\btalents?\b.*\b(?:books?|materials?|crowns?|cost)\b",
    re.I,
)
_TALENT_RANGE = re.compile(
    r"\b(?:from\s+)?(?:level\s+|lv\.?\s*)?(\d{1,2})\s*(?:to|-|→)\s*(?:level\s+|lv\.?\s*)?(\d{1,2})\b",
    re.I,
)
_FARM_TODAY = re.compile(
    r"\b(?:farm\w*|domains?|books?)\b.{0,40}\btoday\b|\btoday\b.{0,40}\b(?:farm\w*|domains?)\b",
    re.I,
)
_ROSTER = re.compile(r"\(My showcased characters: (.+?)\)(?: \(My server: (\w+)\))?")


def _formula(section: str) -> Citation:
    return Citation(
        1,
        "KQM damage formula",
        FORMULAS,
        "kqm",
        f"kqm/combat-mechanics/damage/damage-formula#{section}",
    )


def em_bonus(em: int, reaction: str) -> float:
    top, offset = REACTIONS[reaction.lower()]
    return top * em / (offset + em)


def def_multiplier(character: int, enemy: int, reduction: float = 0.0) -> float:
    return (character + 100) / ((character + 100) + (enemy + 100) * (1 - reduction))


def res_multiplier(resistance: float) -> float:
    if resistance < 0:
        return 1 - resistance / 2
    if resistance < 0.75:
        return 1 - resistance
    return 1 / (4 * resistance + 1)


def _em_answer(q: str) -> Answer | None:
    reaction, em = _REACTION.search(q), _EM.search(q)
    if not reaction or not em:
        return None
    value = int(em.group(1) or em.group(2))
    name = reaction.group(1).lower()
    bonus = em_bonus(value, name)
    top, offset = REACTIONS[name]
    label = {"vape": "Vaporize", "overload": "Overloaded"}.get(name, name.capitalize())
    section = {_AMPLIFYING: "amplifying-reaction", _TRANSFORMATIVE: "transformative-reaction"}
    text = (
        f"**{value} EM adds {bonus:.1%} to {label}.** [1]\n\n"
        f"- Working: {top} × {value} ÷ ({offset} + {value}) = {bonus:.4f}\n"
        "- This is the EM part only. Set bonuses such as Crimson Witch add on top. [1]"
    )
    trace = {"intent": "calc", "calc": "em"}
    return Answer(
        text, "exact", [_formula(section.get(REACTIONS[name], "additive-reaction"))], trace
    )


def _def_answer(q: str) -> Answer | None:
    levels = _LEVELS.search(q)
    if not _DEF_ASK.search(q) or not levels:
        return None
    character, enemy = int(levels.group(1)), int(levels.group(2))
    cut = _DEF_CUT.search(q)
    reduction = min(int(cut.group(1)), 90) / 100 if cut else 0.0  # hard capped at 90%
    mult = def_multiplier(character, enemy, reduction)
    shred = f" with {reduction:.0%} DEF reduction" if reduction else ""
    text = (
        f"**A Lv.{character} character against a Lv.{enemy} enemy{shred} deals {mult:.1%} damage "
        f"through DEF.** [1]\n\n"
        f"- Working: ({character} + 100) ÷ (({character} + 100) + ({enemy} + 100) × "
        f"(1 − {reduction:.2f})) = {mult:.4f}\n"
        "- DEF reduction is capped at 90%. [1]"
    )
    return Answer(text, "exact", [_formula("enemy-defense")], {"intent": "calc", "calc": "def"})


def _res_answer(q: str) -> Answer | None:
    base = _RES.search(q)
    if not _RES_ASK.search(q) or not base:
        return None
    cut = _RES_CUT.search(q)
    resistance = (int(base.group(1)) - (int(cut.group(1)) if cut else 0)) / 100
    mult = res_multiplier(resistance)
    text = (
        f"**At {resistance:.0%} resistance, the enemy takes {mult:.1%} damage.** [1]\n\n"
        "- Below 0: 1 − RES ÷ 2. From 0 up to 75%: 1 − RES. From 75%: 1 ÷ (4 × RES + 1). [1]"
    )
    return Answer(text, "exact", [_formula("enemy-resistance")], {"intent": "calc", "calc": "res"})


def _talent_answer(q: str, planner: dict | None) -> Answer | None:
    costs = (planner or {}).get("talent_costs")
    span = _TALENT_RANGE.search(q)
    if not costs or not _TALENT.search(q) or not span:
        return None
    start, end = int(span.group(1)), int(span.group(2))
    if not 1 <= start < end <= len(costs) + 1:
        return None
    rows = costs[start - 1 : end - 1]
    teachings, guides, philosophies, weekly, crowns = (sum(r[i] for r in rows) for i in range(5))
    text = (
        f"**One talent from level {start} to {end} takes {teachings} Teachings, {guides} Guides "
        f"and {philosophies} Philosophies.** [1]\n\n"
        f"- It also takes {weekly} weekly boss drops and {crowns} Crown of Insight. [1]\n"
        "- That's for one talent, and it leaves out Mora and enemy drops. A few characters, such "
        "as the Traveler, have their own costs."
    )
    cite = Citation(1, "Talent level costs", SCHEDULE, "official", "planner#talent_costs")
    return Answer(text, "exact", [cite], {"intent": "calc", "calc": "talent"})


def calculate(question: str, planner: dict | None, formulas: bool = True) -> Answer | None:
    """An exact sum if the question gives every number one needs. `formulas` is off when KQM
    content is switched off, because those sums are theirs."""
    if planner and (talent := _talent_answer(question, planner)):
        return talent
    if not formulas:
        return None
    return _em_answer(question) or _def_answer(question) or _res_answer(question)


# ---- what to farm today ------------------------------------------------------------------
def server_of(uid: str) -> str:
    """Genshin UIDs start with their server's digit."""
    return {"6": "america", "7": "europe"}.get(uid[:1], "asia")


def server_weekday(planner: dict, server: str, now: datetime) -> int:
    """Monday 1 to Sunday 7, on the game's day: it turns over at the daily reset."""
    reset = planner["reset"]
    local = now.astimezone(UTC) + timedelta(hours=reset["servers"][server] - reset["hour"])
    return local.isoweekday()


def farm_today(question: str, planner: dict | None, names, now: datetime) -> Answer | None:
    """Whose talent books are open today, for the characters in a public showcase.

    `names` turns the showcase text into official names.
    """
    if not planner or not _FARM_TODAY.search(question):
        return None
    found = _ROSTER.search(question)
    if not found or not found.group(2):
        text = (
            "**Share your UID and I'll match today's domains to your characters.** I read only "
            "your public showcase. The Daily planner also shows what's open today."
        )
        return Answer(text, "exact", [], {"intent": "farm_today"})
    server = found.group(2).lower()
    day = server_weekday(planner, server, now)
    by_name = {c["name"]: c for c in planner["characters"]}
    open_now, later = [], []
    for name in names(found.group(1)):
        c = by_name.get(name)
        book = (
            planner["books"].get((c or {}).get("books", [""])[0]) if c and c.get("books") else None
        )
        if not book:
            continue
        line = f"**{name}**: {book['items'][0]} series at {book['domain']}"
        (open_now if day == 7 or day in book["days"] else later).append(line)
    place = server.capitalize()
    cite = Citation(1, "Domain schedule", SCHEDULE, "official", "planner#books")
    if not open_now and not later:
        return None
    if open_now:
        count = len(open_now)
        text = f"**On {place} servers today, {count} showcased characters can farm books.** [1]\n\n"
        text += "\n".join(f"- {line}" for line in open_now)
    else:
        text = f"**No showcased talent books are open on {place} servers today.** [1]\n\n"
        text += "\n".join(f"- {line} (another day)" for line in later)
    text += "\n\nI can only see the characters you display in your in-game showcase."
    return Answer(text, "exact", [cite], {"intent": "farm_today"})
