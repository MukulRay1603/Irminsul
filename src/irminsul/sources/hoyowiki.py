"""Official HoYoWiki (wiki.hoyolab.com), HoYoverse's own wiki, via its public JSON API.

Used for three things:
- the official name lists that confirm undated Yatta weapons and artifact sets,
- officially announced characters that are not playable yet (status ANNOUNCED),
- official video collections (trailers, demos) for UI embeds.

Announced characters only ever get an overview: kit modules (talents, constellations,
ascension) are not turned into docs, and pages flagged `beta` are skipped entirely.
Parsing is kept in pure functions so it can be tested against saved fixtures.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from irminsul.schema import (
    BaseStats,
    Character,
    Constellation,
    Release,
    ReleaseStatus,
    ScalingRow,
    SourceRef,
    Talent,
    Tier,
    Video,
    slugify,
)
from irminsul.sources.http import PoliteClient

log = logging.getLogger(__name__)

API = "https://sg-wiki-api-static.hoyolab.com/hoyowiki/genshin/wapi"
PAGE_URL = "https://wiki.hoyolab.com/pc/genshin/entry/{}"
HEADERS = {"x-rpc-language": "en-us", "Referer": "https://wiki.hoyolab.com/"}

# Menu ids of the entry lists (checked Oct 26 2026: 132 characters, 252 weapons, 63 sets).
MENU_CHARACTERS = "2"
MENU_WEAPONS = "4"
MENU_ARTIFACTS = "5"

KIT_MODULES = {"Talents", "Constellation", "Ascend"}
# Hub pages that are not a playable character of their own.
NOT_CHARACTERS = {"traveler"}
_HTML_TAG = re.compile(r"<[^>]+>")
_YOUTUBE_ID = re.compile(r"(?:v=|youtu\.be/|/embed/|/shorts/)([\w-]{11})")


@dataclass
class OfficialEntry:
    entry_id: str
    name: str
    filters: dict[str, list[str]] = field(default_factory=dict)

    def first(self, key: str) -> str | None:
        values = self.filters.get(key) or []
        return values[0] if values else None


def parse_entry(raw: dict[str, Any]) -> OfficialEntry:
    filters = {
        key: list((value or {}).get("values") or [])
        for key, value in (raw.get("filter_values") or {}).items()
    }
    return OfficialEntry(entry_id=str(raw["entry_page_id"]), name=raw["name"], filters=filters)


def _component_payload(component: dict[str, Any]) -> Any:
    data = component.get("data") or ""
    try:
        return json.loads(data) if data else None
    except json.JSONDecodeError:
        return data


def _has_content(payload: Any) -> bool:
    if isinstance(payload, dict):
        return any(_has_content(v) for v in payload.values())
    if isinstance(payload, list):
        return any(_has_content(v) for v in payload)
    if isinstance(payload, str):
        return bool(payload.strip())
    return payload is not None


def page_has_kit(page: dict[str, Any]) -> bool:
    """True if any kit module (talents, constellations, ascension) has real content."""
    for module in page.get("modules") or []:
        if module.get("name") in KIT_MODULES:
            for component in module.get("components") or []:
                if component.get("component_id") == "map":
                    continue  # ascension map pins are not kit content
                if _has_content(_component_payload(component)):
                    return True
    return False


def youtube_id(url: str) -> str | None:
    m = _YOUTUBE_ID.search(url or "")
    return m.group(1) if m else None


def parse_videos(page: dict[str, Any], entity_id: str, fetched_at: datetime) -> list[Video]:
    videos: list[Video] = []
    source = SourceRef(
        source="hoyowiki",
        url=PAGE_URL.format(page.get("id")),
        tier=Tier.OFFICIAL,
        fetched_at=fetched_at,
    )
    for module in page.get("modules") or []:
        for component in module.get("components") or []:
            if component.get("component_id") != "video_collection":
                continue
            payload = _component_payload(component) or {}
            for group in payload.get("list") or []:
                for v in group.get("videos") or []:
                    if not v.get("url"):
                        continue
                    videos.append(
                        Video(
                            entity_id=entity_id,
                            group=group.get("name") or "",
                            title=v.get("title") or "",
                            url=v["url"],
                            youtube_id=youtube_id(v["url"]),
                            thumbnail=v.get("img") or None,
                            source=source,
                        )
                    )
    return videos


def announced_character(
    entry: OfficialEntry, page: dict[str, Any], fetched_at: datetime
) -> Character | None:
    """An officially revealed, not-yet-playable character. Beta pages return None."""
    if page.get("beta"):
        return None
    rarity = entry.first("character_rarity") or ""
    return Character(
        id=f"character/{slugify(entry.name)}",
        game_id=f"hoyowiki:{entry.entry_id}",
        name=entry.name,
        rarity=int(m.group()) if (m := re.search(r"\d", rarity)) else 0,
        element=entry.first("character_vision") or "",
        weapon_type=entry.first("character_weapon") or "",
        region=entry.first("character_region"),
        summary=_HTML_TAG.sub("", page.get("desc") or "").strip() or None,
        release=Release(status=ReleaseStatus.ANNOUNCED),
        source=SourceRef(
            source="hoyowiki",
            url=PAGE_URL.format(entry.entry_id),
            tier=Tier.OFFICIAL,
            fetched_at=fetched_at,
        ),
    )


def _module(page: dict[str, Any], name: str, component: str) -> list[dict[str, Any]]:
    for module in page.get("modules") or []:
        if module.get("name") == name:
            for c in module.get("components") or []:
                if c.get("component_id") == component:
                    payload = _component_payload(c)
                    return (payload or {}).get("list") or [] if isinstance(payload, dict) else []
    return []


def _clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    return _HTML_TAG.sub("", text).strip()


def _attribute(page: dict[str, Any], key: str) -> str | None:
    for row in _module(page, "Attributes", "baseInfo"):
        if row.get("key") == key and row.get("value"):
            return _clean(row["value"][0]) or None
    return None


def _talents(page: dict[str, Any]) -> list[Talent]:
    """HoYoWiki lists Normal Attack, Skill, Burst, then passives, in that order."""
    kinds = ["normal_attack", "skill", "burst"]
    talents = []
    for i, raw in enumerate(_module(page, "Talents", "talent")):
        rows = []
        for attr in raw.get("attributes") or []:
            if attr.get("key") == "Level":
                continue
            values = attr.get("values") or []
            rows.append(ScalingRow(label=attr["key"], by_level=dict(enumerate(values, 1))))
        talents.append(
            Talent(
                kind=kinds[i] if i < len(kinds) else "passive",
                name=raw.get("title") or "",
                description=_clean(raw.get("desc")),
                scaling=rows,
            )
        )
    return talents


def _constellations(page: dict[str, Any]) -> list[Constellation]:
    return [
        Constellation(level=i, name=c.get("name") or "", description=_clean(c.get("desc")))
        for i, c in enumerate(_module(page, "Constellation", "summaryList"), 1)
    ]


def _base_stats(page: dict[str, Any]) -> BaseStats | None:
    rows = _module(page, "Ascend", "ascension")
    top = next((r for r in rows if r.get("key") == "Lv.90"), None)
    if top is None:
        return None
    stats = {}
    for row in top.get("combatList") or []:
        values = row.get("values") or []
        if row.get("key") and values:
            stats[row["key"]] = values[0]
    try:
        hp, atk, defense = (float(stats.pop(k)) for k in ("Base HP", "Base ATK", "Base DEF"))
    except (KeyError, ValueError):
        return None
    bonus_stat, bonus_value = None, None
    for key, value in stats.items():
        bonus_stat = key.removesuffix(" Bonus").strip()
        number = float(value.rstrip("%"))
        bonus_value = number / 100 if value.endswith("%") else number
    return BaseStats(
        level=90, hp=hp, atk=atk, defense=defense, bonus_stat=bonus_stat, bonus_value=bonus_value
    )


def released_character(
    entry: OfficialEntry, page: dict[str, Any], fetched_at: datetime, released_at: datetime
) -> Character | None:
    """A playable character built from their official page, for when the game-data mirrors
    haven't caught up. Only for characters an official wish notice proves are live."""
    base = announced_character(entry, page, fetched_at)
    talents, constellations = _talents(page), _constellations(page)
    if base is None or not talents or len(constellations) != 6:
        return None
    return base.model_copy(
        update={
            "title": _attribute(page, "Title"),
            "base_stats": _base_stats(page),
            "talents": talents,
            "constellations": constellations,
            "release": Release(status=ReleaseStatus.RELEASED, released_at=released_at),
        }
    )


class HoYoWikiSource:
    def __init__(self, client: PoliteClient) -> None:
        self.client = client

    def entries(self, menu_id: str, page_size: int = 50) -> list[OfficialEntry]:
        out: list[OfficialEntry] = []
        page_num = 1
        while True:
            body = {
                "filters": [],
                "menu_id": menu_id,
                "page_num": page_num,
                "page_size": page_size,
                "use_es": True,
            }
            data = self._unwrap(self.client.post_json(f"{API}/get_entry_page_list", body))
            batch = data.get("list") or []
            out += [parse_entry(raw) for raw in batch]
            if not batch or len(out) >= int(data.get("total") or 0):
                return out
            page_num += 1

    def page(self, entry_id: str) -> dict[str, Any]:
        data = self._unwrap(
            self.client.get_json(f"{API}/entry_page", params={"entry_page_id": entry_id})
        )
        return data["page"]

    @staticmethod
    def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("retcode") != 0:
            raise ValueError(f"HoYoWiki retcode={payload.get('retcode')}: {payload.get('message')}")
        return payload["data"]
