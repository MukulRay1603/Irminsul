"""Structured cards for exact answers, so the page can present data instead of a text dump.

A card carries everything needed to switch views without another request: a talent card holds
every talent, a weapon card all five refinements, a constellation card C1 to C6. Values are
pre-formatted strings, so every client shows the same numbers. Only released entities get full
cards; an announced character gets the overview card the leak gate allows.
"""

from irminsul.schema import ArtifactSet, Character, Talent, Weapon

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
                **_scaling(t),
            }
            for t in c.talents
        ],
    }


def _scaling(t: Talent) -> dict:
    """Scaling rows as one value per level, aligned to `levels`, for the level slider."""
    levels = sorted({lvl for row in t.scaling for lvl in row.by_level})
    if not levels:
        return {"levels": [], "scaling": []}
    return {
        "levels": levels,
        "scaling": [
            {"label": row.label, "values": [row.by_level.get(lvl, "-") for lvl in levels]}
            for row in t.scaling
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


def _row(label: str, values: list[str], nums: list[float | None] | None = None) -> dict:
    """One comparison row. `best` marks the highest number, unless they are all equal."""
    best: list[int] = []
    if nums and None not in nums and len(set(nums)) > 1:
        top = max(nums)
        best = [i for i, n in enumerate(nums) if n == top]
    return {"label": label, "values": values, "best": best}


def _stat_row(label: str, stats: list[str | None], values: list[float | None]) -> dict:
    """A secondary/ascension stat row: numbers only compete when the stat is the same."""
    if len(set(stats)) == 1 and stats[0]:
        return _row(stats[0], [pct(v, stats[0]) for v in values], values)
    return _row(
        label, [f"{s} {pct(v, s)}" if s else "-" for s, v in zip(stats, values, strict=True)]
    )


def _flat(values: list[float | None]) -> list[str]:
    return ["-" if v is None else f"{v:,.0f}" for v in values]


def compare_card(kind: str, entities: list) -> dict:
    """Side by side data for 2-3 released entities of one kind. Never a recommendation."""
    if kind == "character":
        stats = [c.base_stats for c in entities]
        columns = [
            {**_head(c), "sub": " · ".join(x for x in (c.element, c.weapon_type) if x)}
            for c in entities
        ]

        def get(attr):
            return [getattr(s, attr) if s else None for s in stats]

        level = next((s.level for s in stats if s), 90)
        rows = [
            _row("Base HP", _flat(get("hp")), get("hp")),
            _row("Base ATK", _flat(get("atk")), get("atk")),
            _row("Base DEF", _flat(get("defense")), get("defense")),
            _stat_row("Ascension stat", get("bonus_stat"), get("bonus_value")),
        ]
        kicker = f"Level {level} base stats"
    elif kind == "weapon":
        columns = [
            {"entity": w.id, "name": w.name, "rarity": w.rarity, "sub": w.weapon_type}
            for w in entities
        ]
        atk = [w.base_atk for w in entities]
        rows = [
            _row("Base ATK", _flat(atk), atk),
            _stat_row(
                "Secondary stat",
                [w.secondary_stat for w in entities],
                [w.secondary_value for w in entities],
            ),
            _row("Passive", [w.passive_name or "-" for w in entities]),
        ]
        kicker = "Weapons at max level"
    else:
        columns = [
            {
                "entity": a.id,
                "name": a.name,
                "rarity": max(a.rarities, default=0),
                "sub": "Artifact set",
            }
            for a in entities
        ]
        pieces = sorted({n for a in entities for n in a.bonuses})
        rows = [
            {**_row(f"{n}-piece", [a.bonuses.get(n, "-") for a in entities]), "text": True}
            for n in pieces
        ]
        kicker = "Artifact set bonuses"
    return {
        "type": "compare",
        "kind": kind,
        "kicker": kicker,
        "columns": columns,
        "rows": rows,
        "note": "A side-by-side of official game data, not a recommendation.",
    }


def announced_card(c: Character) -> dict:
    return {"type": "announced", **_head(c)}
