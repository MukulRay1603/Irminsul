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

from irminsul.schema import Character, Release, ReleaseStatus, SourceRef, Tier, Video, slugify
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
