"""Tests that keep themselves current.

An answer that changes with the game (is a character out yet, whose banner is next) is never
typed into the eval set: the item names where to look, and the expected answer is read from
the build the test runs against. Items that no longer apply are set aside and listed, so they
never fail a gate for being out of date, and never silently vanish either.

Lookups (`live` on an item):
- {"entity": id, "field": "element"}: the record's value must appear. A released record is
  expected to be answered; an announced one is a partial answer ("official so far").
- {"entity": id, "check": "playable"}: released means "playable" plus the version it came in;
  announced means the answer must say it isn't out yet.
- {"banners": "next"}: if official wish notices name the next version's 5-stars, the answer
  must name them; else it must say they aren't announced.

Any question may say {live}, {next} or {next2} (two versions on): they become real versions,
so "Who are the leaked {next} characters?" stays a leak probe after every patch.
"""

import json
from pathlib import Path

from irminsul.evals import EvalItem, Expect

NOT_OUT = ["not out", "not playable", "isn't playable", "not yet", "announced", "upcoming"]
NOT_ANNOUNCED = ["hasn't announced", "not announced", "haven't been announced"]
MINORS_PER_MAJOR = 8  # x.0 to x.7


def _key(version: str) -> tuple[int, int]:
    major, minor = version.split(".")[:2]
    return int(major), int(minor)


def next_version(version: str) -> str:
    major, minor = _key(version)
    return f"{major + 1}.0" if minor + 1 >= MINORS_PER_MAJOR else f"{major}.{minor + 1}"


class Build:
    """What the tests read from a corpus build: records, doc ids, the live version, wishes."""

    def __init__(self, path: Path):
        self.records: dict[str, dict] = {}
        for name in ("characters.jsonl", "weapons.jsonl", "artifact_sets.jsonl"):
            f = path / name
            if f.exists():
                for line in f.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        r = json.loads(line)
                        self.records[r["id"]] = r
        self.doc_ids: set[str] | None = None
        docs = path / "docs.jsonl"
        if docs.exists():
            with docs.open(encoding="utf-8") as f:
                self.doc_ids = {json.loads(line)["doc_id"] for line in f if line.strip()}
        feed_file = path / "banners.json"
        self.feed = json.loads(feed_file.read_text(encoding="utf-8")) if feed_file.exists() else {}
        self.live = self._live_version(path)

    def _live_version(self, path: Path) -> str | None:
        versions = []
        manifest = path / "manifest.json"
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            game = data.get("sources", {}).get("yatta", {}).get("game_version") or ""
            if len(game) >= 2 and game[:2].isdigit():
                versions.append(f"{game[0]}.{game[1]}")
        # The official notices can be a day ahead of the data mirrors on patch day
        versions += list(self.feed.get("versions", {}))
        return max(versions, key=_key, default=None)


def _resolve_live(item: EvalItem, build: Build) -> EvalItem | str:
    spec = item.live or {}
    update: dict = {}
    if "entity" in spec:
        record = build.records.get(spec["entity"])
        if record is None:
            return f"{spec['entity']} isn't in this build"
        released = record.get("release", {}).get("status") == "released"
        if spec.get("check") == "playable":
            if released:
                groups = [["playable"]]
                if record.get("revealed_in"):
                    groups.append([record["revealed_in"]])
            else:
                groups = [NOT_OUT]
            update = {"expect": Expect.ANSWER if released else Expect.PARTIAL}
        else:
            value = record.get(spec.get("field", ""))
            if not isinstance(value, str) or not value:
                return f"{spec['entity']} has no {spec.get('field')!r}"
            groups = [[value]]
            update = {"expect": Expect.ANSWER if released else Expect.PARTIAL}
        update["must_include"] = item.must_include + groups
    elif spec.get("banners") == "next":
        if build.live is None:
            return "no live version in this build"
        upcoming = next_version(build.live)  # the question already says it via {next}
        named = [
            name
            for b in build.feed.get("banners", [])
            if b.get("version") == upcoming and b.get("kind") == "character"
            for name in b.get("five_stars", [])
        ]
        groups = [[n] for n in dict.fromkeys(named)] or [NOT_ANNOUNCED]
        update = {"must_include": item.must_include + groups}
    else:
        return f"unknown lookup {spec}"
    return item.model_copy(update=update)


_PLACEHOLDERS = ("{live}", "{next}", "{next2}")


def _versions(item: EvalItem, live: str) -> EvalItem:
    if not any(p in item.question for p in _PLACEHOLDERS):
        return item
    after = next_version(live)
    question = (
        item.question.replace("{live}", live)
        .replace("{next2}", next_version(after))
        .replace("{next}", after)
    )
    return item.model_copy(update={"question": question, "game_version": live})


def _needs_build(item: EvalItem) -> bool:
    return item.live is not None or any(p in item.question for p in _PLACEHOLDERS)


def resolve(items: list[EvalItem], build_path: Path | None) -> tuple[list[EvalItem], list[dict]]:
    """Items as they apply to this build, and the ones set aside, each with the reason."""
    if build_path is None or not build_path.exists():
        # No build to read: lookups can't be answered, everything else runs as written
        kept = [i for i in items if not _needs_build(i)]
        aside = [
            {"id": i.id, "reason": "needs a build to look up"} for i in items if _needs_build(i)
        ]
        return kept, aside
    build = Build(build_path)
    kept: list[EvalItem] = []
    aside: list[dict] = []
    for item in items:
        if item.valid_while and build.live and _key(build.live) > _key(item.valid_while):
            aside.append({"id": item.id, "reason": f"only true up to {item.valid_while}"})
            continue
        if _needs_build(item):
            if build.live is None:
                aside.append({"id": item.id, "reason": "no live version in this build"})
                continue
            item = _versions(item, build.live)
        if item.live is not None:
            resolved = _resolve_live(item, build)
            if isinstance(resolved, str):
                aside.append({"id": item.id, "reason": resolved})
                continue
            item = resolved
        if item.gold_doc_ids and build.doc_ids is not None:
            present = [d for d in item.gold_doc_ids if d in build.doc_ids]
            if not present and not item.must_include:
                aside.append({"id": item.id, "reason": "its source docs are no longer published"})
                continue
            if present != item.gold_doc_ids:
                item = item.model_copy(update={"gold_doc_ids": present})
        kept.append(item)
    return kept, aside
