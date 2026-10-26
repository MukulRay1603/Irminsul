"""The daily planner's data: which domain drops each character's talent books, and on which days.

The web planner works out "what can I farm today" on the player's device. This module gives it
the facts to do that, as one compact `planner.json` per build:

- talent book series (from each character's talent level-up costs) with their Domain of Mastery
  and weekdays, plus each character's weekly boss material
- weapon ascension material series with their Domain of Forgery and weekdays
- the talent level-up cost table, so the planner can count the books a goal still needs

The weekdays come from Yatta's daily domain schedule (`dailyDungeon`). Only characters and
weapons that passed the leak gate as released are passed in, and only the series they use are
written, so nothing here can name unreleased content. Everything is pure and fixture-tested.
"""

from collections import Counter
from collections.abc import Iterable
from typing import Any

from irminsul.schema import Character, ReleaseStatus, Weapon

PLANNER_VERSION = 1
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
NOT_DROPS = {"102", "105", "202"}  # Adventure EXP, Companionship EXP, Mora
MORA = "202"
CROWN = "104319"  # Crown of Insight
# Daily reset is 04:00 server time; offsets are the servers' fixed UTC offsets (no DST).
RESET = {"hour": 4, "servers": {"america": -5, "europe": 1, "asia": 8}}
TALENT_LEVELS = range(2, 11)  # talent levels 2..10 cost books; 11+ only comes from constellations


def parse_schedule(daily: dict[str, Any]) -> list[dict[str, Any]]:
    """Group the weekly domain schedule into one entry per reward series.

    Yatta lists, per weekday, each domain variant and its rewards. A series (e.g. the three
    "Light" books) is farmed from one variant on two weekdays; Sunday opens every variant.
    """
    series: dict[frozenset[str], dict[str, Any]] = {}
    for day_no, day in enumerate(WEEKDAYS[:6], start=1):  # Sunday is "everything", not a slot
        for domain in (daily.get(day) or {}).values():
            items = frozenset(str(i) for i in domain.get("reward") or []) - NOT_DROPS
            if not items:
                continue
            name = str(domain.get("name") or "")
            kind, _, variant = name.partition(": ")
            entry = series.setdefault(
                items,
                {
                    "kind": "mastery" if "Mastery" in kind else "forgery",
                    "items": items,
                    "domain": variant or name,
                    "city": domain.get("city"),
                    "days": [],
                },
            )
            if day_no not in entry["days"]:
                entry["days"].append(day_no)
    return list(series.values())


def _costs(promotes: Iterable[dict[str, Any]]) -> Counter[str]:
    total: Counter[str] = Counter()
    for p in promotes:
        total.update({str(k): v for k, v in (p.get("costItems") or {}).items()})
    return total


def _talent_promotes(data: dict[str, Any]) -> list[dict[str, Any]]:
    """The level-up cost rows of the first talent that has any (all three share one table)."""
    for _, t in sorted((data.get("talent") or {}).items(), key=lambda kv: int(kv[0])):
        promote = t.get("promote") or {}
        rows = [promote[str(lvl)] for lvl in TALENT_LEVELS if str(lvl) in promote]
        if any(r.get("costItems") for r in rows):
            return rows
    return []


def character_materials(data: dict[str, Any]) -> dict[str, Any]:
    """Item ids a character uses, from a Yatta avatar record.

    `talent` holds every item in the talent costs; the weekly boss drop is the one item
    there that is not a book (books are matched to domains later), not common enemy loot
    (which ascension also uses), and not Mora or the Crown.
    """
    rows = _talent_promotes(data)
    talent = _costs(rows)
    ascension = _costs((data.get("upgrade") or {}).get("promote") or [])
    items = {str(k): v for k, v in (data.get("items") or {}).items()}
    return {
        "talent": list(talent),
        "ascension": list(ascension),
        "talent_rows": [{str(k): v for k, v in (r.get("costItems") or {}).items()} for r in rows],
        "items": {k: {"name": v.get("name"), "rank": v.get("rank")} for k, v in items.items()},
    }


def weapon_materials(data: dict[str, Any]) -> dict[str, Any]:
    ascension = _costs((data.get("upgrade") or {}).get("promote") or [])
    items = {str(k): v for k, v in (data.get("items") or {}).items()}
    return {
        "ascension": list(ascension),
        "items": {k: {"name": v.get("name"), "rank": v.get("rank")} for k, v in items.items()},
    }


BOOK_PREFIXES = ("Teachings of the ", "Teachings of ", "Guide to the ", "Guide to ")


def _series_name(items: list[str], names: dict[str, str]) -> str:
    """ "Light" for the Teachings/Guide/Philosophies of Light; weapon series: their first item."""
    known = [names[i] for i in items if i in names]
    if not known:
        return items[0]
    for name in known:
        for prefix in BOOK_PREFIXES:
            if name.startswith(prefix):
                return name.removeprefix(prefix).strip("\"'“”")
    return known[0]


def build_planner(
    characters: Iterable[Character],
    char_materials: dict[str, dict[str, Any]],
    weapons: Iterable[Weapon],
    weap_materials: dict[str, dict[str, Any]],
    schedule: list[dict[str, Any]],
    game_version: str | None = None,
    built_at: str | None = None,
) -> dict[str, Any]:
    """The planner payload. Callers pass gated records; announced characters are skipped here."""
    by_item = {item: entry for entry in schedule for item in entry["items"]}
    used: dict[str, dict[str, Any]] = {}  # series key -> schedule entry
    names: dict[str, str] = {}  # item id -> name, merged across every record that uses it
    regions: dict[str, Counter[str]] = {}
    tables: dict[str, list[list]] = {}
    out_chars = []

    def series(item: str, kind: str) -> str | None:
        """Series key: the lowest item id (ids rise with rarity, so it is the 2-star item)."""
        entry = by_item.get(item)
        if not entry or entry["kind"] != kind:
            return None
        key = min(entry["items"])
        used[key] = entry
        return key

    def remember(items: dict[str, dict[str, Any]]) -> None:
        names.update({k: v["name"] for k, v in items.items() if v.get("name")})

    for c in characters:
        mats = char_materials.get(c.id)
        if c.release.status != ReleaseStatus.RELEASED or mats is None:
            continue
        items = mats["items"]
        remember(items)
        book_keys: list[str] = []
        book_items: set[str] = set()
        for item in mats["talent"]:
            if key := series(item, "mastery"):
                book_items.add(item)
                if key not in book_keys:
                    book_keys.append(key)
                    if c.region:
                        region = c.region.split("_")[0]  # e.g. "Snezhnaya_Star"
                        regions.setdefault(key, Counter())[region] += 1
        # The weekly boss drop: the 5-star talent material that isn't the Crown.
        weekly = next(
            (
                i
                for i in sorted(set(mats["talent"]) - book_items - {MORA, CROWN})
                if (items.get(i) or {}).get("rank") == 5
            ),
            None,
        )
        # Talent costs counted by book rarity (2, 3, 4 star), so the Traveler, whose talents
        # use several series, fits the same table.
        rank_of = {
            i: items[i]["rank"] - 2
            for i in book_items
            if (items.get(i) or {}).get("rank") in (2, 3, 4)
        }
        rows = []
        for row in mats["talent_rows"]:
            counts = [0, 0, 0]
            for item, n in row.items():
                if item in rank_of:
                    counts[rank_of[item]] += n
            rows.append([*counts, row.get(weekly, 0) if weekly else 0, row.get(CROWN, 0)])
        table_key = repr(rows)
        tables.setdefault(table_key, rows)
        out_chars.append(
            {
                "id": c.id,
                "name": c.name,
                "element": c.element,
                "rarity": c.rarity,
                "weapon_type": c.weapon_type,
                "books": book_keys,
                "weekly": names.get(weekly) if weekly else None,
                "_table": table_key,
            }
        )

    # One shared cost table; a character whose table differs carries its own.
    common = Counter(c["_table"] for c in out_chars).most_common(1)
    common_key = common[0][0] if common else None
    for c in out_chars:
        key = c.pop("_table")
        if key != common_key:
            c["talent_costs"] = tables[key]

    out_weapons = []
    weapon_keys: set[str] = set()
    for w in weapons:
        mats = weap_materials.get(w.id)
        if w.release.status != ReleaseStatus.RELEASED or mats is None:
            continue
        key = next((k for i in mats["ascension"] if (k := series(i, "forgery"))), None)
        if key:
            remember(mats["items"])
            weapon_keys.add(key)
            out_weapons.append(
                {
                    "id": w.id,
                    "name": w.name,
                    "rarity": w.rarity,
                    "weapon_type": w.weapon_type,
                    "material": key,
                }
            )

    def describe(key: str) -> dict[str, Any]:
        entry = used[key]
        items = sorted(entry["items"])
        out = {
            "name": _series_name(items, names),
            "items": [names.get(i, i) for i in items],
            "domain": entry["domain"],
            "days": sorted(entry["days"]),
        }
        if key in regions:
            out["region"] = regions[key].most_common(1)[0][0]
        return out

    book_keys_all = {k for c in out_chars for k in c["books"]}
    out_chars.sort(key=lambda c: c["name"])
    out_weapons.sort(key=lambda w: (-w["rarity"], w["name"]))
    return {
        "version": PLANNER_VERSION,
        "game_version": game_version,
        "built_at": built_at,
        "reset": RESET,
        "talent_costs": tables[common_key] if common_key else [],
        "books": {k: describe(k) for k in sorted(book_keys_all)},
        "weapon_materials": {k: describe(k) for k in sorted(weapon_keys)},
        "characters": out_chars,
        "weapons": out_weapons,
    }
