"""Render entities into retrievable Markdown docs with stable ids."""

from irminsul.schema import ArtifactSet, Character, Doc, ReleaseStatus, Weapon, slugify

TALENT_TITLES = {
    "normal_attack": "Normal Attack",
    "skill": "Elemental Skill",
    "burst": "Elemental Burst",
    "passive": "Passive Talent",
    "special": "Special Talent",
}


def _pct(value: float | None, stat: str | None) -> str:
    if value is None:
        return "-"
    if stat == "Elemental Mastery":
        return f"{value:.0f}"
    return f"{value * 100:.1f}%"


def character_docs(c: Character) -> list[Doc]:
    common = {"entity_id": c.id, "release": c.release, "source": c.source}
    descriptor = " ".join(
        part for part in (f"{c.rarity}★" if c.rarity else "", c.element, c.weapon_type) if part
    )
    lines = [
        f"# {c.name}" + (f" — {c.title}" if c.title else ""),
        f"{descriptor} character" + (f" from {c.region}" if c.region else "") + ".",
    ]
    if c.release.status == ReleaseStatus.ANNOUNCED:
        lines.append(
            "Officially announced by HoYoverse but not yet playable. Only officially "
            "published information is included; the full kit is not official yet."
        )
    if c.summary:
        lines.append(c.summary)
    if c.release.released_at:
        lines.append(f"Released: {c.release.released_at:%Y-%m-%d}.")
    if s := c.base_stats:
        lines.append(
            f"Base stats at Lv. {s.level}: HP {s.hp:.0f}, ATK {s.atk:.0f}, DEF {s.defense:.0f}, "
            f"{s.bonus_stat} {_pct(s.bonus_value, s.bonus_stat)} (ascension stat)."
        )
    if c.talents:
        lines.append(
            "Talents: "
            + "; ".join(f"{TALENT_TITLES.get(t.kind, t.kind)}: {t.name}" for t in c.talents)
            + "."
        )
    docs = [
        Doc(
            doc_id=f"{c.id}#overview",
            kind="character_overview",
            title=f"{c.name} overview",
            text="\n".join(lines),
            **common,
        )
    ]

    for t in c.talents:
        body = [f"# {c.name} — {TALENT_TITLES.get(t.kind, t.kind)}: {t.name}", t.description]
        if t.scaling:
            levels = sorted({lvl for row in t.scaling for lvl in row.by_level})
            body.append("\n| Attribute | " + " | ".join(f"Lv{lvl}" for lvl in levels) + " |")
            body.append("|---|" + "---|" * len(levels))
            for row in t.scaling:
                body.append(
                    f"| {row.label} | "
                    + " | ".join(row.by_level.get(lvl, "-") for lvl in levels)
                    + " |"
                )
        docs.append(
            Doc(
                doc_id=f"{c.id}#talent-{t.kind}-{slugify(t.name)}",
                kind="talent",
                title=f"{c.name}: {t.name}",
                text="\n".join(body),
                **common,
            )
        )

    if c.constellations:
        body = [f"# {c.name} — Constellations"]
        body += [f"\n## C{con.level}: {con.name}\n{con.description}" for con in c.constellations]
        docs.append(
            Doc(
                doc_id=f"{c.id}#constellations",
                kind="constellations",
                title=f"{c.name} constellations",
                text="\n".join(body),
                **common,
            )
        )
    return docs


def weapon_docs(w: Weapon) -> list[Doc]:
    lines = [f"# {w.name}", f"{w.rarity}★ {w.weapon_type}."]
    if w.base_atk:
        sub = (
            f", {w.secondary_stat} {_pct(w.secondary_value, w.secondary_stat)}"
            if w.secondary_stat
            else ""
        )
        lines.append(f"Max level stats: Base ATK {w.base_atk:.0f}{sub}.")
    if w.passive_name and w.passive_by_refinement:
        lines.append(f"\n## Passive: {w.passive_name}")
        lines += [f"R{i}: {text}" for i, text in enumerate(w.passive_by_refinement, 1)]
    if w.description:
        lines.append(f"\n{w.description}")
    return [
        Doc(
            doc_id=f"{w.id}#main",
            entity_id=w.id,
            kind="weapon",
            title=w.name,
            text="\n".join(lines),
            release=w.release,
            source=w.source,
        )
    ]


def artifact_docs(a: ArtifactSet) -> list[Doc]:
    rarity = "/".join(f"{r}★" for r in a.rarities)
    lines = [f"# {a.name} (artifact set)", f"Available rarities: {rarity}."]
    lines += [f"{n}-Piece Bonus: {text}" for n, text in sorted(a.bonuses.items())]
    return [
        Doc(
            doc_id=f"{a.id}#main",
            entity_id=a.id,
            kind="artifact_set",
            title=a.name,
            text="\n".join(lines),
            release=a.release,
            source=a.source,
        )
    ]
