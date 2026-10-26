"""Patch notes: what each game version added or changed, from official data only.

Two sources, combined per version:
- release history: characters carry Yatta's official release timestamp, mapped to a version
  with the official release-date table in versions.py. This reconstructs every past version.
- the change history (`history.json`, written by the daily build): weapons, artifact sets and
  official videos added, and before/after for records that changed, since tracking began.

Released content only. Every entity is checked against the loaded store, so a stale or edited
history can never name a record the leak gate holds back. Announced characters appear only by
name, element and region (what the official overview shows), never with kit details. Nothing
dated after `now` is included.
"""

import re
from datetime import UTC, date, datetime
from typing import Any

from irminsul.engine.entities import EntityStore, Match
from irminsul.schema import ReleaseStatus
from irminsul.versions import SOURCE_URL, key, released_versions, version_of

MAX_VIDEOS = 12  # per version
_VERSION_TITLE = re.compile(r"\bVersion (\d+\.\d+)\b")
KIND_GROUP = {"character": "characters", "weapon": "weapons", "artifact": "artifact_sets"}


def _released(store: EntityStore, entity_id: str) -> Match | None:
    m = store.by_id.get(entity_id)
    if m is None or m.entity.release.status != ReleaseStatus.RELEASED:
        return None
    return m


def _item(m: Match, released_at: str | None = None) -> dict[str, Any]:
    e = m.entity
    item = {
        "id": e.id,
        "kind": m.kind,
        "name": e.name,
        "source": e.source.url,
        "tier": e.source.tier,
    }
    if m.kind == "character":
        item.update(rarity=e.rarity, element=e.element, weapon_type=e.weapon_type)
    elif m.kind == "weapon":
        item.update(rarity=e.rarity, weapon_type=e.weapon_type)
    else:
        item.update(rarity=max(e.rarities, default=0))
    if released_at:
        item["released_at"] = released_at
    return item


def _video(v: dict) -> dict[str, Any]:
    return {
        "entity_id": v["entity_id"],
        "title": v["title"],
        "url": v["url"],
        "youtube_id": v.get("youtube_id"),
        "group": v.get("group"),
    }


def _empty(version: str, start: date, live: bool) -> dict[str, Any]:
    return {
        "version": version,
        "date": start.isoformat(),
        "live": live,
        "source": SOURCE_URL,
        "characters": [],
        "weapons": [],
        "artifact_sets": [],
        "changes": [],
        "videos": [],
        "tracked": False,
    }


def build_patch_notes(
    store: EntityStore,
    history: dict | None,
    videos: dict[str, list[dict]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Every released version, newest first, with what it added and changed."""
    now = now or datetime.now(UTC)
    today = now.astimezone(UTC).date()
    videos = videos or {}
    entries = [
        e
        for e in (history or {}).get("entries", [])
        if e.get("version") and e.get("date", "9999") <= today.isoformat()
    ]
    # Versions the table doesn't list yet start on the day the history first saw them.
    seen: dict[str, date] = {}
    for e in entries:
        seen.setdefault(e["version"], date.fromisoformat(e["date"]))
    starts = released_versions(now, seen)
    live = max(starts, key=key) if starts else None
    notes = {v: _empty(v, d, v == live) for v, d in starts.items()}

    # 1. New characters, from official release timestamps
    for m in store.by_id.values():
        when = m.entity.release.released_at
        if m.kind != "character" or when is None or not _released(store, m.entity.id):
            continue
        if when > now:
            continue
        version = version_of(when, starts)
        if version in notes:
            notes[version]["characters"].append(_item(m, when.astimezone(UTC).isoformat()))

    # 2. Weapons, sets, changes and videos, from the change history
    by_url = {v["url"]: v for vs in videos.values() for v in vs}
    changes: dict[tuple[str, str], dict] = {}  # (version, id) -> merged change
    for e in entries:
        note = notes.get(e["version"])
        if note is None:
            continue
        for entity_id in e.get("added", []):
            m = _released(store, entity_id)
            group = KIND_GROUP.get(m.kind) if m else None
            if group and not any(x["id"] == entity_id for x in note[group]):
                note[group].append(_item(m))
        for entity_id in e.get("changed", []):
            m = _released(store, entity_id)
            if m is None:
                continue
            merged = changes.setdefault(
                (e["version"], entity_id),
                {**_item(m), "dates": [], "fields": []},
            )
            merged["dates"].append(e["date"])
            for f in e.get("changes", {}).get(entity_id, []):
                old = next((x for x in merged["fields"] if x["field"] == f["field"]), None)
                if old:
                    old["after"] = f["after"]  # earliest before, latest after
                else:
                    merged["fields"].append(dict(f))
        for url in e.get("videos", []):
            v = by_url.get(url)
            if v and _released(store, v["entity_id"]):
                note["videos"].append(_video(v))

    # Tracked = the history covers the whole version, so its weapons and sets are complete.
    since = min((e["date"] for e in entries), default=None)
    for note in notes.values():
        note["tracked"] = since is not None and note["date"] >= since

    for (version, entity_id), change in changes.items():
        new_here = any(x["id"] == entity_id for g in KIND_GROUP.values() for x in notes[version][g])
        change["fields"] = [f for f in change["fields"] if f["before"] != f["after"]]
        if not new_here:
            notes[version]["changes"].append(change)

    # 3. Official videos of what each version added (trailers, character demos)
    for note in notes.values():
        have = {v["url"] for v in note["videos"]}
        for c in note["characters"] + note["weapons"]:
            for v in videos.get(c["id"], []):
                # A character page also links other versions' trailers: keep this version's
                named = _VERSION_TITLE.search(v["title"])
                if named and named.group(1) != note["version"]:
                    continue
                if v["url"] not in have:
                    note["videos"].append(_video(v))
                    have.add(v["url"])
        note["videos"] = note["videos"][:MAX_VIDEOS]
        for group in ("characters", "weapons", "artifact_sets"):
            note[group].sort(key=lambda x: (-x.get("rarity", 0), x["name"]))
        note["changes"].sort(key=lambda x: x["name"])

    announced = [
        {
            "id": m.entity.id,
            "name": m.entity.name,
            "element": m.entity.element,
            "region": m.entity.region,
            "source": m.entity.source.url,
        }
        for m in store.by_id.values()
        if m.kind == "character" and m.entity.release.status == ReleaseStatus.ANNOUNCED
    ]
    return {
        "live": live,
        "generated_at": now.astimezone(UTC).isoformat(),
        "tracking_since": since,
        "versions_source": SOURCE_URL,
        "versions": sorted(notes.values(), key=lambda n: key(n["version"]), reverse=True),
        "announced": sorted(announced, key=lambda a: a["name"]),
    }
