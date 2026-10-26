"""Structured cards for exact answers, so the page can present data instead of a text dump.

A card carries everything needed to switch views without another request: a talent card holds
every talent, a weapon card all five refinements, a constellation card C1 to C6. Values are
pre-formatted strings, so every client shows the same numbers. Only released entities get full
cards; an announced character gets the overview card the leak gate allows.
"""

from irminsul.schema import ArtifactSet, Character, Weapon

TALENT_LABEL = {
    "normal_attack": "Normal Attack",
    "skill": "Elemental Skill",
    "burst": "Elemental Burst",
    "passive": "Passive",
}


def pct(value: float | None, stat: str | None) -> str:
    if value is None:
        return "-"
    return f"{value:.0f}" if stat == "Elemental Mastery" else f"{value * 100:.1f}%"


def _head(c: Character) -> dict:
    return {
        "entity": c.id,
        "name": c.name,
        "title": c.title,
        "rarity": c.rarity,
        "element": c.element,
        "weapon_type": c.weapon_type,
        "region": c.region,
    }


def stats_card(c: Character) -> dict:
    s = c.base_stats
    return {
        "type": "stats",
        **_head(c),
        "level": s.level,
        "stats": [
            {"label": "Base HP", "value": f"{s.hp:,.0f}"},
            {"label": "Base ATK", "value": f"{s.atk:,.0f}"},
            {"label": "Base DEF", "value": f"{s.defense:,.0f}"},
        ],
        "highlight": {
            "label": s.bonus_stat or "Ascension stat",
            "value": pct(s.bonus_value, s.bonus_stat),
        },
    }


def talents_card(c: Character, selected: str) -> dict:
    return {
        "type": "talents",
        **_head(c),
        "selected": selected,
        "tabs": [
            {"key": kind, "label": label}
            for kind, label in TALENT_LABEL.items()
            if any(t.kind == kind for t in c.talents)
        ],
        "talents": [
            {
                "kind": t.kind,
                "label": TALENT_LABEL.get(t.kind, t.kind),
                "name": t.name,
                "description": t.description,
            }
            for t in c.talents
        ],
    }


def constellations_card(c: Character, selected: int) -> dict:
    return {
        "type": "constellations",
        **_head(c),
        "selected": selected,
        "items": [
            {"level": x.level, "name": x.name, "description": x.description}
            for x in sorted(c.constellations, key=lambda x: x.level)
        ],
    }


def weapon_card(w: Weapon, refinement: int) -> dict:
    return {
        "type": "weapon",
        "entity": w.id,
        "name": w.name,
        "rarity": w.rarity,
        "weapon_type": w.weapon_type,
        "stats": [
            {"label": "Base ATK", "value": "-" if w.base_atk is None else f"{w.base_atk:,.0f}"}
        ]
        + (
            [{"label": w.secondary_stat, "value": pct(w.secondary_value, w.secondary_stat)}]
            if w.secondary_stat
            else []
        ),
        "passive_name": w.passive_name,
        "refinements": list(w.passive_by_refinement),
        "selected": refinement,
    }


def set_card(a: ArtifactSet) -> dict:
    return {
        "type": "set",
        "entity": a.id,
        "name": a.name,
        "bonuses": [{"pieces": int(n), "text": t} for n, t in sorted(a.bonuses.items())],
    }


def announced_card(c: Character) -> dict:
    return {"type": "announced", **_head(c)}
