"""Exact answers from the entity store, plus the overview-only answer for announced characters.

Only questions about a single named entity with a clear stat or passive intent, or a data
comparison of 2-3 released entities of one kind, are answered here; anything else ("is X good",
"which is better for Raiden", builds) goes to retrieval + LLM.
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
# Comparisons: "vs" and "compare" ask for a side-by-side on their own; "or" and "better" only
# when the question also asks for numbers. Anything that asks for advice goes to retrieval.
_COMPARE = re.compile(
    r"\bvs\b|\bversus\b|\bcompar(?:e|ed|ing|ison)\b|\bdifference between\b|\bdiffer\b", re.I
)
_COMPARE_WEAK = re.compile(r"\bor\b|\bbetter\b|\bhigher\b|\bmore\b", re.I)
_COMPARE_DATA = {
    "character": _STATS,
    "weapon": re.compile(
        r"\bbase (atk|attack|stats?)\b|\bstats?\b|\batk\b|\bsecondary\b|\bsub ?stats?\b"
        r"|\bpassives?\b",
        re.I,
    ),
    "artifact": re.compile(r"\b[24][- ]?(pc|piece)\b|\bset bonus(es)?\b|\bbonus(es)?\b", re.I),
}
_OPINION = re.compile(
    r"\bshould\b|\bworth\b|\brecommend|\bbest\b|\bgood\b|\bstronger\b|\bpull\b|\bbuild\b"
    r"|\bteams?\b|\bmeta\b|\btier\b|\bwho wins\b|\bfor (?:my|a|an|the)\b",
    re.I,
)
_COMPARE_MAX = 3
# "What changed in 7.1?", "What's new this patch?", "New characters in 6.0": patch notes, when
# the question is about a version (or is just "what's new?") and asks for no opinion.
_PATCH_ASK = re.compile(
    r"\bnew\b|\bchang(?:e|ed|es)\b|\badded\b|\breleased?\b|\bcame out\b|\bpatch notes?\b"
    r"|\bchangelog\b",
    re.I,
)
_PATCH_SCOPE = re.compile(
    r"\bpatch\b|\bversion\b|\bupdate\b|\bv?\d\.\d\b|\bchangelog\b"
    r"|^\W*what(?:['’]?s| is| has)? (?:new|changed)\W*$",
    re.I,
)
_PATCH_VERSION = re.compile(r"\b(?:version |v|patch )?(\d)\.(\d)\b", re.I)
_PATCH_SHOWN = 8  # items named per group in the text answer


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
    # "What are X's constellations?": describing all six is a lookup ("best one?" is not)
    if re.search(r"\bconstellations?\b", q, re.I) and _DESCRIBE.search(q) and c.constellations:
        names = "\n".join(
            f"- **C{x.level}:** {x.name}" for x in sorted(c.constellations, key=lambda x: x.level)
        )
        return Answer(
            f"**{c.name}'s constellations**\n{names} [1]",
            "exact",
            [_cite(m, "constellations")],
            {"entity": c.id, "intent": "const_all"},
            card=cards.constellations_card(c, 1),
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


def _compare_line(kind: str, e) -> str:
    if kind == "character":
        s = e.base_stats
        if not s:
            return f"- **{e.name}:** no base stats in the data"
        return (
            f"- **{e.name}:** HP {s.hp:,.0f}, ATK {s.atk:,.0f}, DEF {s.defense:,.0f}, "
            f"{s.bonus_stat} {_pct(s.bonus_value, s.bonus_stat)}"
        )
    if kind == "weapon":
        atk = "-" if e.base_atk is None else f"{e.base_atk:,.0f}"
        sub = f", {e.secondary_stat} {_pct(e.secondary_value, e.secondary_stat)}"
        passive = f", passive {e.passive_name}" if e.passive_name else ""
        return f"- **{e.name}:** base ATK {atk}{sub if e.secondary_stat else ''}{passive}"
    bonuses = "; ".join(f"{n}-piece: {t}" for n, t in sorted(e.bonuses.items()))
    return f"- **{e.name}:** {bonuses}"


def compare_answer(matches: list[Match], q: str) -> Answer | None:
    """Side by side data for 2-3 released entities of one kind, when the question asks for it.

    Opinions ("which is better for Raiden?") are left to retrieval: this compares numbers and
    effect text from the game data and says so.
    """
    kinds = {m.kind for m in matches}
    if not (2 <= len(matches) <= _COMPARE_MAX) or len(kinds) != 1:
        return None
    if not all(released(m) for m in matches):
        return None  # the leak gate's release status decides; announced entities never compete
    kind = kinds.pop()
    data = _COMPARE_DATA[kind].search(q)
    if _OPINION.search(q) or (re.search(r"\bbetter\b", q, re.I) and not data):
        return None
    if not (_COMPARE.search(q) or (data and _COMPARE_WEAK.search(q))):
        return None
    entities = [m.entity for m in matches]
    what = {
        "character": "Level 90 base stats",
        "weapon": "Max-level stats",
        "artifact": "Set bonuses",
    }[kind]
    lines = [f"**{' vs '.join(e.name for e in entities)}**", "", f"{what}:"]
    lines += [_compare_line(kind, e) for e in entities]
    refs = "".join(f"[{i}]" for i in range(1, len(entities) + 1))
    lines += ["", f"This is a data comparison from the game files, not a recommendation. {refs}"]
    doc = {"character": "overview", "weapon": "main", "artifact": "main"}[kind]
    return Answer(
        "\n".join(lines),
        "exact",
        [
            Citation(i, e.name, e.source.url, e.source.tier, f"{e.id}#{doc}")
            for i, e in enumerate(entities, start=1)
        ],
        {"entities": [e.id for e in entities], "intent": f"compare:{kind}"},
        card=cards.compare_card(kind, entities),
    )


def is_patch_question(question: str) -> bool:
    return bool(
        _PATCH_ASK.search(question)
        and _PATCH_SCOPE.search(question)
        and not _OPINION.search(question)
    )


def _names(items: list[dict], cite: dict[str, int]) -> str:
    shown = [
        f"{x['name']}" + (f" [{cite[x['id']]}]" if x["id"] in cite else "")
        for x in items[:_PATCH_SHOWN]
    ]
    more = len(items) - _PATCH_SHOWN
    return ", ".join(shown) + (f" and {more} more" if more > 0 else "")


def _long_date(iso: str) -> str:
    y, m, d = (int(x) for x in iso[:10].split("-"))
    months = "January February March April May June July August September October November December"
    return f"{d} {months.split()[m - 1]} {y}"


def patch_answer(notes: dict | None, question: str) -> Answer | None:
    """Patch notes for one version, straight from the data: no AI, and released content only."""
    if not notes or not notes.get("live"):
        return None
    asked = _PATCH_VERSION.search(question)
    version = f"{asked.group(1)}.{asked.group(2)}" if asked else notes["live"]
    note = next((n for n in notes["versions"] if n["version"] == version), None)
    official = Citation(1, "Official version update notices", notes["versions_source"], "official")
    trace = {"intent": "patch", "version": version}
    if note is None:
        live = tuple(int(x) for x in notes["live"].split("."))
        if tuple(int(x) for x in version.split(".")) <= live:
            text = f"There is no Version {version} in HoYoverse's official release history. [1]"
            return Answer(text, "exact", [official], trace)
        names = [a["name"] for a in notes.get("announced", [])]
        text = (
            f"**Version {version} isn't out yet**, so there are no patch notes for it. "
            f"The live version is {notes['live']}."
        )
        if names:
            text += (
                " Officially announced by HoYoverse but not playable yet: "
                + ", ".join(names)
                + ". Their kits aren't official until release."
            )
        card = cards.patch_card({"version": version, "upcoming": True}, notes)
        return Answer(text + " [1]", "exact", [official], trace, card=card)

    citations = [official]
    cite: dict[str, int] = {}
    for x in note["characters"] + note["weapons"] + note["artifact_sets"] + note["changes"]:
        if len(citations) > 3 * _PATCH_SHOWN or x["id"] in cite:
            continue
        cite[x["id"]] = len(citations) + 1
        citations.append(
            Citation(len(citations) + 1, x["name"], x["source"], x["tier"], f"{x['id']}#patch")
        )
    when = "went live" if not note["live"] else "is the live version; it went live"
    lines = [f"**Version {version}** {when} on {_long_date(note['date'])}. [1]", ""]
    groups = (
        ("New characters", note["characters"]),
        ("New weapons", note["weapons"]),
        ("New artifact sets", note["artifact_sets"]),
    )
    for label, items in groups:
        if items:
            lines.append(f"- **{label}:** {_names(items, cite)}")
    if note["changes"]:
        changed = [
            f"{c['name']}"
            + (f" ({', '.join(f['field'] for f in c['fields'][:3])})" if c["fields"] else "")
            + (f" [{cite[c['id']]}]" if c["id"] in cite else "")
            for c in note["changes"][:_PATCH_SHOWN]
        ]
        lines.append("- **Changed:** " + "; ".join(changed))
    if note["videos"]:
        n = len(note["videos"])
        lines.append(f"- **New official videos:** {n}")
    if len(lines) == 2:
        lines.append("- Nothing new in the released data for this version.")
    if not note["tracked"] and notes.get("tracking_since"):
        lines += [
            "",
            "New weapons, artifact sets and balance changes are tracked from "
            f"{_long_date(notes['tracking_since'])}; before that, patch notes list new "
            "characters from their official release dates.",
        ]
    return Answer(
        "\n".join(lines),
        "exact",
        citations,
        trace,
        card=cards.patch_card(note, notes),
    )


def answer_exact(store: EntityStore, question: str, patches: dict | None = None) -> Answer | None:
    matches = store.find(question)
    if not matches and is_patch_question(question):
        return patch_answer(patches, question)
    if not matches:
        return None
    announced = [
        m
        for m in matches
        if m.kind == "character" and m.entity.release.status == ReleaseStatus.ANNOUNCED
    ]
    if announced:
        return announced_answer(announced[0])
    if len(matches) > 1:
        return compare_answer(matches, question)  # anything but a data comparison: retrieval
    if not released(matches[0]):
        return None
    m = matches[0]
    handler = {"character": character_answer, "weapon": weapon_answer, "artifact": artifact_answer}[
        m.kind
    ]
    return handler(m, question)
