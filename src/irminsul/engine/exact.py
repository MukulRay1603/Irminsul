"""Exact answers from the entity store, plus the overview-only answer for announced characters.

Only questions about a single named entity with a clear stat or passive intent are answered
here; anything else (comparisons, "is X good", builds) goes to retrieval + LLM.
"""

import re

from irminsul.engine import cards
from irminsul.engine.entities import EntityStore, Match, released
from irminsul.engine.types import Answer, Citation
from irminsul.schema import ReleaseStatus, slugify

_STATS = re.compile(
    r"\bbase (atk|attack|hp|def|defen[cs]e|stats?)\b|\blevel 90\b|\blv\.? ?90\b|\bascension\b"
    r"|\bstats?\b|\bhow much (hp|atk|def)\b",
    re.I,
)
_KIND = re.compile(r"\belement\b|\bvision\b|\bweapon type\b|\bwhat weapon\b", re.I)
_CONST = re.compile(r"\bc([1-6])\b|\bconstellation ([1-6])\b", re.I)
_PASSIVE = re.compile(
    r"\bpassive\b|\brefinement\b|\br[1-5]\b|\bwhat does\b|\beffect\b|\bwho gets\b", re.I
)
# "What does X's Burst do?": describing a talent is a lookup; judging one ("is it good") is not.
_TALENT = re.compile(
    r"\b(?P<burst>(?:elemental )?burst|ultimate)\b|\b(?P<skill>(?:elemental )?skill)\b"
    r"|\b(?P<normal_attack>normal attacks?|auto attacks?)\b|\b(?P<passive>passives?)\b",
    re.I,
)
_DESCRIBE = re.compile(r"\bwhat (?:does|do|is|are)\b|\bdescribe\b|\bexplain\b|\bdetails?\b", re.I)
_SET = re.compile(r"\b[24][- ]?(pc|piece)\b|\bset bonus\b|\bbonus\b|\bwhat does\b", re.I)


def _pct(value: float | None, stat: str | None) -> str:
    if value is None:
        return "-"
    return f"{value:.0f}" if stat == "Elemental Mastery" else f"{value * 100:.1f}%"


def _cite(m: Match, doc_suffix: str) -> Citation:
    e = m.entity
    return Citation(1, e.name, e.source.url, e.source.tier, f"{e.id}#{doc_suffix}")


def announced_answer(m: Match) -> Answer:
    c = m.entity
    where = f" from {c.region}" if c.region else ""
    element = f"an {c.element}" if c.element[:1].lower() in "aeiou" else f"a {c.element}"
    text = (
        f"**{c.name}** has been officially announced by HoYoverse as {element} character{where}, "
        f"but is **not playable yet**. Their talents, constellations and other kit details are "
        f"not official yet, so I won't guess or share leaked information. [1]"
    )
    return Answer(
        text,
        "announced",
        [_cite(m, "overview")],
        {"entity": c.id, "status": "announced"},
        card=cards.announced_card(c),
    )


_TALENT_LABEL = {
    "burst": "Elemental Burst",
    "skill": "Elemental Skill",
    "normal_attack": "Normal Attack",
    "passive": "passive talents",
}


def character_answer(m: Match, q: str) -> Answer | None:
    c = m.entity
    if (con := _CONST.search(q)) and c.constellations:
        level = int(con.group(1) or con.group(2))
        cons = next((x for x in c.constellations if x.level == level), None)
        if cons:
            return Answer(
                f"**{c.name} C{level}: {cons.name}**\n\n{cons.description} [1]",
                "exact",
                [_cite(m, "constellations")],
                {"entity": c.id, "intent": "const"},
                card=cards.constellations_card(c, level),
            )
    if _STATS.search(q) and c.base_stats:
        s = c.base_stats
        text = (
            f"**{c.name}** ({c.rarity}★ {c.element} {c.weapon_type}) at Lv. {s.level}: "
            f"base HP {s.hp:.0f}, base ATK {s.atk:.0f}, base DEF {s.defense:.0f}. "
            f"Ascension stat: {s.bonus_stat} {_pct(s.bonus_value, s.bonus_stat)}. [1]"
        )
        return Answer(
            text,
            "exact",
            [_cite(m, "overview")],
            {"entity": c.id, "intent": "stats"},
            card=cards.stats_card(c),
        )
    if (talent := _TALENT.search(q)) and _DESCRIBE.search(q) and c.talents:
        kind = talent.lastgroup
        chosen = [t for t in c.talents if t.kind == kind]
        if chosen:
            parts = [f"**{t.name}**\n{t.description}" for t in chosen]
            return Answer(
                f"{c.name}'s {_TALENT_LABEL[kind]}:\n\n" + "\n\n".join(parts) + " [1]",
                "exact",
                [_cite(m, f"talent-{kind}-{slugify(chosen[0].name)}")],
                {"entity": c.id, "intent": f"talent:{kind}"},
                card=cards.talents_card(c, kind),
            )
    if _KIND.search(q):
        text = (
            f"**{c.name}** is a {c.rarity}★ {c.element} character who uses a {c.weapon_type}. [1]"
        )
        return Answer(text, "exact", [_cite(m, "overview")], {"entity": c.id, "intent": "kind"})
    return None


def weapon_answer(m: Match, q: str) -> Answer | None:
    w = m.entity
    wants_passive = bool(_PASSIVE.search(q))
    if not (wants_passive or _STATS.search(q) or re.search(r"\bsecondary|sub ?stat", q, re.I)):
        return None
    sub = (
        f", {w.secondary_stat} {_pct(w.secondary_value, w.secondary_stat)}"
        if w.secondary_stat
        else ""
    )
    lines = [
        f"**{w.name}** ({w.rarity}★ {w.weapon_type}): base ATK {w.base_atk:.0f}{sub} "
        f"at max level. [1]"
    ]
    r = re.search(r"\br([1-5])\b", q, re.I)
    level = int(r.group(1)) if r else 1
    if w.passive_name and w.passive_by_refinement:
        lines.append(f"\n**{w.passive_name} (R{level}):** {w.passive_by_refinement[level - 1]} [1]")
    return Answer(
        "\n".join(lines),
        "exact",
        [_cite(m, "main")],
        {"entity": w.id, "intent": "passive" if wants_passive else "stats"},
        card=cards.weapon_card(w, level),
    )


def artifact_answer(m: Match, q: str) -> Answer | None:
    a = m.entity
    if not _SET.search(q):
        return None
    lines = [f"**{a.name}**"] + [f"- **{n}-Piece:** {t}" for n, t in sorted(a.bonuses.items())]
    return Answer(
        "\n".join(lines) + " [1]",
        "exact",
        [_cite(m, "main")],
        {"entity": a.id, "intent": "set"},
        card=cards.set_card(a),
    )


def answer_exact(store: EntityStore, question: str) -> Answer | None:
    matches = store.find(question)
    if not matches:
        return None
    announced = [
        m
        for m in matches
        if m.kind == "character" and m.entity.release.status == ReleaseStatus.ANNOUNCED
    ]
    if announced:
        return announced_answer(announced[0])
    if len(matches) != 1 or not released(matches[0]):
        return None  # comparisons and multi-entity questions need retrieval
    m = matches[0]
    handler = {"character": character_answer, "weapon": weapon_answer, "artifact": artifact_answer}[
        m.kind
    ]
    return handler(m, question)
