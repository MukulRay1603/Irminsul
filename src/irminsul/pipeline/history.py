"""The corpus change history (`history.json`): one dated entry per published change.

Each daily build is compared with the published one (see diff.py). When characters, weapons,
artifact sets or official videos changed, an entry is appended with the record ids that were
added, removed or changed, the game version, and for changed records a short before/after of
the fields that moved (stats, talent text, passives, set bonuses). The file ships with the
dataset, so tomorrow's build appends to today's and "what changed this patch" can be answered
from it.

Only released records count as added: an announced character is never listed, and its release
day shows up as "added", not as a change to the announced overview.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from irminsul.versions import from_data_version

HISTORY_SCHEMA = 1
MAX_ENTRIES = 1000
MAX_TEXT = 1500  # characters kept per before/after value
ENTITY_FILES = ("characters.jsonl", "weapons.jsonl", "artifact_sets.jsonl")
ENTITY_PREFIXES = ("character/", "weapon/", "artifact/")

Records = dict[str, dict[str, Any]]  # entity id -> record as JSON


def load_records(folder: Path) -> Records | None:
    """Entity records from a build folder, or None if it has none (e.g. no previous build)."""
    out: Records = {}
    found = False
    for name in ENTITY_FILES:
        path = folder / name
        if not path.exists():
            continue
        found = True
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                out[row["id"]] = row
    return out if found else None


def load_video_urls(folder: Path) -> set[str] | None:
    path = folder / "videos.jsonl"
    if not path.exists():
        return None
    return {
        json.loads(line)["url"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def load_history(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {"schema": HISTORY_SCHEMA, "entries": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"schema": HISTORY_SCHEMA, "entries": list(data.get("entries", []))}


def _clip(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1].rstrip() + "…"


def _num(value: Any, digits: int = 0) -> str:
    return "-" if value is None else f"{value:,.{digits}f}"


def _pct(value: float | None, stat: str | None) -> str:
    if value is None:
        return "-"
    return f"{value:.0f}" if stat == "Elemental Mastery" else f"{value * 100:.1f}%"


def _level(item: tuple[str, str]) -> int:
    return int(item[0])


def _fields(kind: str, r: dict) -> dict[str, str]:
    """The comparable fields of a record, as display strings keyed by a readable label."""
    out: dict[str, str] = {}
    if kind == "character":
        s = r.get("base_stats") or {}
        if s:
            out["Base HP"] = _num(s.get("hp"))
            out["Base ATK"] = _num(s.get("atk"))
            out["Base DEF"] = _num(s.get("defense"))
            stat = s.get("bonus_stat")
            out["Ascension stat"] = f"{stat} {_pct(s.get('bonus_value'), stat)}" if stat else "-"
        for t in r.get("talents", []):
            out[t["name"]] = t.get("description", "")
            if t.get("scaling"):
                rows = [
                    f"{row['label']}: "
                    + ", ".join(v for _, v in sorted(row["by_level"].items(), key=_level))
                    for row in t["scaling"]
                ]
                out[f"{t['name']} (scaling)"] = "\n".join(rows)
        for c in r.get("constellations", []):
            out[f"C{c['level']} {c['name']}"] = c.get("description", "")
    elif kind == "weapon":
        out["Base ATK"] = _num(r.get("base_atk"))
        stat = r.get("secondary_stat")
        if stat:
            out["Secondary stat"] = f"{stat} {_pct(r.get('secondary_value'), stat)}"
        for i, text in enumerate(r.get("passive_by_refinement", []), start=1):
            out[f"{r.get('passive_name') or 'Passive'} R{i}"] = text
    else:
        for pieces, text in sorted(r.get("bonuses", {}).items()):
            out[f"{pieces}-piece"] = text
    return out


def field_changes(kind: str, old: dict, new: dict) -> list[dict[str, str]]:
    """Before/after for every field that differs between two versions of one record."""
    before, after = _fields(kind, old), _fields(kind, new)
    changes = []
    for label in [*before, *(k for k in after if k not in before)]:
        a, b = before.get(label, ""), after.get(label, "")
        if a != b:
            changes.append({"field": label, "before": _clip(a), "after": _clip(b)})
    return changes


def _kind(entity_id: str) -> str:
    return entity_id.split("/", 1)[0]


def _entities(manifest: dict) -> dict[str, set[str]]:
    """Entity id -> its doc hashes, from a manifest."""
    out: dict[str, set[str]] = {}
    for doc_id, h in manifest.get("doc_hashes", {}).items():
        if doc_id.startswith(ENTITY_PREFIXES):
            out.setdefault(doc_id.split("#", 1)[0], set()).add(f"{doc_id}={h}")
    return out


def _released(ids: set[str], records: Records | None) -> set[str]:
    if records is None:
        return ids  # no records to check: trust the manifest (the leak gate already ran)
    return {i for i in ids if (records.get(i) or {}).get("release", {}).get("status") == "released"}


def make_entry(
    old: dict,
    new: dict,
    old_records: Records | None = None,
    new_records: Records | None = None,
    old_videos: set[str] | None = None,
    new_videos: set[str] | None = None,
) -> dict | None:
    """The history entry for this build, or None if no entity or video changed.

    A first build (no previous manifest) gives a baseline entry: everything would be "added",
    which says nothing about a patch.
    """
    built = new.get("built_at") or datetime.now().isoformat()
    data_version = new.get("sources", {}).get("yatta", {}).get("game_version")
    entry: dict[str, Any] = {
        "date": built[:10],
        "version": from_data_version(data_version),
        "data_version": data_version,
    }
    if not old.get("doc_hashes"):
        return {**entry, "baseline": True}
    old_e, new_e = _entities(old), _entities(new)
    before = _released(set(old_e), old_records)
    after = _released(set(new_e), new_records)
    changed = sorted(i for i in before & after if old_e[i] != new_e[i])
    changes = {}
    if old_records is not None and new_records is not None:
        for i in sorted(before & after):
            if i in old_records and i in new_records:
                diff = field_changes(_kind(i), old_records[i], new_records[i])
                if diff:
                    changes[i] = diff
        changed = sorted(set(changed) | set(changes))
    videos = sorted(new_videos - old_videos) if old_videos is not None and new_videos else []
    entry.update(
        added=sorted(after - before),
        removed=sorted(before - after),
        changed=changed,
        changes=changes,
        videos=videos,
    )
    if not (entry["added"] or entry["removed"] or changed or videos):
        return None
    return entry


def accumulate(history: dict, entry: dict | None) -> dict:
    """Append an entry (None: nothing changed, the history is kept as it is).

    Entries are never merged or replaced: each one is a diff against the build that was
    published at the time, so a second run on the same day only adds what changed since.
    """
    entries = list(history.get("entries", []))
    if entry is not None:
        entries.append(entry)
    return {"schema": HISTORY_SCHEMA, "entries": entries[-MAX_ENTRIES:]}


def update(old: dict, new: dict, old_dir: Path, new_dir: Path, history_in: Path | None) -> dict:
    """Read both builds' records and the published history; return the new history."""
    entry = make_entry(
        old,
        new,
        load_records(old_dir) if old else None,
        load_records(new_dir),
        load_video_urls(old_dir) if old else None,
        load_video_urls(new_dir),
    )
    return accumulate(load_history(history_in), entry)
