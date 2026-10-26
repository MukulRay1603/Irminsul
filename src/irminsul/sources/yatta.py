"""Official in-game data via the Yatta API (gi.yatta.moe).

Yatta serves datamined *live* client data. The default endpoints carry only the
current live version (reported by /static/version), so presence here means
"in the live game". Characters also carry an official release timestamp.
Parsing is kept in pure functions so it can be tested against saved fixtures.
"""

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from irminsul.schema import (
    ArtifactSet,
    BaseStats,
    Character,
    Constellation,
    Release,
    ReleaseStatus,
    ScalingRow,
    SourceRef,
    Talent,
    Tier,
    Weapon,
    slugify,
)
from irminsul.sources.http import PoliteClient
from irminsul.text import clean, fill_params

log = logging.getLogger(__name__)

API = "https://gi.yatta.moe/api/v2"
SITE = "https://gi.yatta.moe/en"

ELEMENTS = {
    "Fire": "Pyro",
    "Water": "Hydro",
    "Wind": "Anemo",
    "Electric": "Electro",
    "Grass": "Dendro",
    "Ice": "Cryo",
    "Rock": "Geo",
}
WEAPON_TYPES = {
    "WEAPON_SWORD_ONE_HAND": "Sword",
    "WEAPON_CLAYMORE": "Claymore",
    "WEAPON_POLE": "Polearm",
    "WEAPON_BOW": "Bow",
    "WEAPON_CATALYST": "Catalyst",
}
STATS = {
    "FIGHT_PROP_HP_PERCENT": "HP%",
    "FIGHT_PROP_ATTACK_PERCENT": "ATK%",
    "FIGHT_PROP_DEFENSE_PERCENT": "DEF%",
    "FIGHT_PROP_CRITICAL": "CRIT Rate",
    "FIGHT_PROP_CRITICAL_HURT": "CRIT DMG",
    "FIGHT_PROP_CHARGE_EFFICIENCY": "Energy Recharge",
    "FIGHT_PROP_ELEMENT_MASTERY": "Elemental Mastery",
    "FIGHT_PROP_HEAL_ADD": "Healing Bonus",
    "FIGHT_PROP_PHYSICAL_ADD_HURT": "Physical DMG Bonus",
    "FIGHT_PROP_FIRE_ADD_HURT": "Pyro DMG Bonus",
    "FIGHT_PROP_WATER_ADD_HURT": "Hydro DMG Bonus",
    "FIGHT_PROP_WIND_ADD_HURT": "Anemo DMG Bonus",
    "FIGHT_PROP_ELEC_ADD_HURT": "Electro DMG Bonus",
    "FIGHT_PROP_GRASS_ADD_HURT": "Dendro DMG Bonus",
    "FIGHT_PROP_ICE_ADD_HURT": "Cryo DMG Bonus",
    "FIGHT_PROP_ROCK_ADD_HURT": "Geo DMG Bonus",
}
FLAT_STATS = {"FIGHT_PROP_ELEMENT_MASTERY"}  # everything else in STATS is a fraction
REGIONS = {
    "MONDSTADT": "Mondstadt",
    "LIYUE": "Liyue",
    "INAZUMA": "Inazuma",
    "SUMERU": "Sumeru",
    "FONTAINE": "Fontaine",
    "NATLAN": "Natlan",
    "SNEZHNAYA": "Snezhnaya",
    "NODKRAI": "Nod-Krai",
    "MAINACTOR": None,
    "RANGER": None,
    "OMNI_SCOURGE": None,
}
TALENT_LEVELS = (1, 6, 9, 10, 13)


def stat_name(prop: str | None) -> str | None:
    if not prop:
        return None
    return STATS.get(prop, prop.removeprefix("FIGHT_PROP_").replace("_", " ").title())


def _curve_value(curves: dict[str, Any], level: int, curve_type: str) -> float:
    return curves[str(level)]["curveInfos"][curve_type]


def compute_stats(upgrade: dict[str, Any], curves: dict[str, Any], level: int) -> dict[str, float]:
    """Stat values at `level`, max ascension: base * growth curve + ascension bonuses."""
    out: dict[str, float] = {}
    for prop in upgrade.get("prop") or []:
        out[prop["propType"]] = prop["initValue"] * _curve_value(curves, level, prop["type"])
    # addProps are cumulative totals per ascension phase, so only the highest phase reached
    # counts. A phase is reached once the level cap before it is below `level`.
    promotes = sorted(upgrade.get("promote") or [], key=lambda p: p.get("promoteLevel", 0))
    reached = [
        p
        for prev, p in zip(promotes, promotes[1:], strict=False)
        if prev.get("unlockMaxLevel", 0) < level
    ]
    if reached:
        for prop, value in (reached[-1].get("addProps") or {}).items():
            out[prop] = out.get(prop, 0.0) + value
    return out


def _talent_kind(t: dict[str, Any], seen_type0: int) -> str:
    if t["type"] == 1:
        return "burst"
    if t["type"] == 2:
        return "passive"
    return ("normal_attack", "skill")[seen_type0] if seen_type0 < 2 else "special"


def parse_talents(raw: dict[str, Any]) -> list[Talent]:
    talents: list[Talent] = []
    seen_type0 = 0
    for _, t in sorted(raw.items(), key=lambda kv: int(kv[0])):
        if not t.get("name"):
            continue
        kind = _talent_kind(t, seen_type0)
        if t["type"] == 0:
            seen_type0 += 1
        scaling: list[ScalingRow] = []
        promote = t.get("promote") or {}
        if promote:
            labels = promote.get("1", {}).get("description") or []
            for row in labels:
                if not row or "|" not in row:
                    continue
                label, template = row.split("|", 1)
                by_level = {
                    lvl: fill_params(template, promote[str(lvl)].get("params") or [])
                    for lvl in TALENT_LEVELS
                    if str(lvl) in promote
                }
                scaling.append(ScalingRow(label=clean(label), by_level=by_level))
        talents.append(
            Talent(
                kind=kind,
                name=clean(t["name"]),
                description=clean(t.get("description")),
                scaling=scaling,
            )
        )
    return talents


def parse_character(
    data: dict[str, Any], curves: dict[str, Any], fetched_at: datetime, game_version: str | None
) -> Character:
    stats = compute_stats(data.get("upgrade") or {}, curves, 90)
    special = data.get("specialProp")
    bonus = stats.get(special) if special else None
    base = BaseStats(
        level=90,
        hp=round(stats.get("FIGHT_PROP_BASE_HP", 0.0)),
        atk=round(stats.get("FIGHT_PROP_BASE_ATTACK", 0.0)),
        defense=round(stats.get("FIGHT_PROP_BASE_DEFENSE", 0.0)),
        bonus_stat=stat_name(special),
        bonus_value=round(bonus, 4) if bonus is not None else None,
    )
    released_at = datetime.fromtimestamp(data["release"], UTC) if data.get("release") else None
    name = data["name"]
    route = data.get("route") or name
    return Character(
        id=f"character/{slugify(name)}",
        game_id=str(data["id"]),
        name=name,
        rarity=int(data.get("rank") or 0),
        element=ELEMENTS.get(data.get("element") or "", data.get("element") or "None"),
        weapon_type=WEAPON_TYPES.get(data.get("weaponType") or "", data.get("weaponType") or ""),
        region=REGIONS.get(data.get("region") or "", (data.get("region") or "").title() or None),
        title=clean((data.get("fetter") or {}).get("title")) or None,
        base_stats=base,
        talents=parse_talents(data.get("talent") or {}),
        constellations=[
            Constellation(
                level=int(k) + 1, name=clean(c["name"]), description=clean(c.get("description"))
            )
            for k, c in sorted((data.get("constellation") or {}).items(), key=lambda kv: int(kv[0]))
        ],
        release=Release(status=ReleaseStatus.RELEASED, released_at=released_at),
        source=SourceRef(
            source="yatta",
            url=f"{SITE}/archive/avatar/{route}",
            tier=Tier.OFFICIAL,
            fetched_at=fetched_at,
            game_version=game_version,
        ),
    )


def parse_weapon(
    data: dict[str, Any], curves: dict[str, Any], fetched_at: datetime, game_version: str | None
) -> Weapon:
    rarity = int(data.get("rank") or 0)
    max_level = 90 if rarity >= 3 else 70
    upgrade = data.get("upgrade") or {}
    stats = compute_stats(upgrade, curves, max_level)
    special = data.get("specialProp")
    secondary = stats.get(special) if special and special != "FIGHT_PROP_NONE" else None
    affixes = list((data.get("affix") or {}).values())
    passive = affixes[0] if affixes else {}
    refinements = [
        clean(passive["upgrade"][k]) for k in sorted((passive.get("upgrade") or {}), key=int)
    ]
    wtype = data.get("type") or ""
    return Weapon(
        id=f"weapon/{slugify(data['name'])}",
        game_id=str(data["id"]),
        name=data["name"],
        rarity=rarity,
        weapon_type=WEAPON_TYPES.get(wtype, wtype),
        base_atk=round(stats.get("FIGHT_PROP_BASE_ATTACK", 0.0)) or None,
        secondary_stat=stat_name(special) if secondary is not None else None,
        secondary_value=round(secondary, 4) if secondary is not None else None,
        passive_name=clean(passive.get("name")) or None,
        passive_by_refinement=refinements,
        description=clean(data.get("description")) or None,
        # Presence in Yatta's live data = in the live game. Weapons carry no release date,
        # so the gate cross-checks them against HoYoWiki before they can be served.
        release=Release(status=ReleaseStatus.RELEASED),
        source=SourceRef(
            source="yatta",
            url=f"{SITE}/archive/weapon/{data['id']}",
            tier=Tier.OFFICIAL,
            fetched_at=fetched_at,
            game_version=game_version,
        ),
    )


def parse_artifact_set(
    data: dict[str, Any], fetched_at: datetime, game_version: str | None
) -> ArtifactSet:
    effects = [clean(v) for _, v in sorted((data.get("affixList") or {}).items())]
    # 1-piece sets (e.g. Prayers) have one effect; regular sets list the 2pc then the 4pc bonus.
    counts = [1] if len(effects) == 1 else [2, 4]
    return ArtifactSet(
        id=f"artifact/{slugify(data['name'])}",
        game_id=str(data["id"]),
        name=data["name"],
        rarities=list(data.get("levelList") or []),
        bonuses=dict(zip(counts, effects, strict=False)),
        release=Release(status=ReleaseStatus.RELEASED),
        source=SourceRef(
            source="yatta",
            url=f"{SITE}/archive/reliquary/{data['id']}",
            tier=Tier.OFFICIAL,
            fetched_at=fetched_at,
            game_version=game_version,
        ),
    )


class YattaSource:
    def __init__(self, client: PoliteClient, lang: str = "en") -> None:
        self.client = client
        self.lang = lang

    def _get(self, path: str) -> Any:
        payload = self.client.get_json(f"{API}/{path}")
        if payload.get("response") != 200:
            raise ValueError(f"Yatta returned response={payload.get('response')} for {path}")
        return payload["data"]

    def game_version(self) -> str:
        return str(self._get("static/version").get("vh"))

    def characters(self, fetched_at: datetime, version: str) -> Iterator[Character]:
        curves = self._get("static/avatarCurve")
        for game_id in self._get(f"{self.lang}/avatar")["items"]:
            try:
                yield parse_character(
                    self._get(f"{self.lang}/avatar/{game_id}"), curves, fetched_at, version
                )
            except Exception:
                log.exception("failed to parse character %s", game_id)

    def weapons(self, fetched_at: datetime, version: str) -> Iterator[Weapon]:
        curves = self._get("static/weaponCurve")
        for game_id, item in self._get(f"{self.lang}/weapon")["items"].items():
            if item.get("isWeaponSkin"):
                continue
            try:
                yield parse_weapon(
                    self._get(f"{self.lang}/weapon/{game_id}"), curves, fetched_at, version
                )
            except Exception:
                log.exception("failed to parse weapon %s", game_id)

    def artifact_sets(self, fetched_at: datetime, version: str) -> Iterator[ArtifactSet]:
        for item in self._get(f"{self.lang}/reliquary")["items"].values():
            yield parse_artifact_set(item, fetched_at, version)
