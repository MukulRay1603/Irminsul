"""Build the corpus: fetch sources -> leak gate -> render docs -> write a versioned snapshot.

Usage:
    uv run irminsul-build --out data/build --cache data/cache
    uv run irminsul-build --limit 5     # quick dev run on a few items per type
    uv run irminsul-build --sources kqm # only some sources (default: all)
"""

import argparse
import itertools
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from irminsul.pipeline.gate import gate, gate_linked_docs, normalise_name
from irminsul.pipeline.guides import reaction_guides
from irminsul.pipeline.planner import build_planner, parse_schedule
from irminsul.pipeline.render import artifact_docs, character_docs, weapon_docs
from irminsul.schema import SCHEMA_VERSION, Character, ReleaseStatus, Video, slugify
from irminsul.sources import hoyowiki
from irminsul.sources.http import PoliteClient
from irminsul.sources.kqm import KqmSource
from irminsul.sources.yatta import YattaSource

log = logging.getLogger("irminsul.build")

SOURCES = ("yatta", "hoyowiki", "kqm")


def _write_jsonl(path: Path, rows: list[BaseModel]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(row.model_dump_json() + "\n")


def check_unique_ids(docs: list) -> None:
    """Doc ids are the upsert key downstream; a repeat would silently overwrite a doc."""
    seen: set[str] = set()
    dupes = sorted({d.doc_id for d in docs if d.doc_id in seen or seen.add(d.doc_id)})
    if dupes:
        raise ValueError(f"{len(dupes)} duplicate doc ids, e.g. {dupes[:5]}")


@dataclass
class Official:
    names: dict[str, set[str]]  # kind -> official names
    announced: list[Character]
    videos: list[Video]
    skipped_beta: list[str]


def fetch_official(
    wiki: hoyowiki.HoYoWikiSource, live: list[Character], now: datetime, limit: int | None
) -> Official:
    """Official name lists, announced characters and official videos from HoYoWiki.

    Announced = on HoYoWiki but not in the live game data. That comparison needs the full
    live roster, so partial (--limit) builds skip it and only sample videos.
    """
    entries = {
        "characters": wiki.entries(hoyowiki.MENU_CHARACTERS),
        "weapons": wiki.entries(hoyowiki.MENU_WEAPONS),
        "artifact_sets": wiki.entries(hoyowiki.MENU_ARTIFACTS),
    }
    live_ids = {normalise_name(c.name): c.id for c in live}
    official = Official({k: {e.name for e in v} for k, v in entries.items()}, [], [], [])
    sampled = 0
    for entry in entries["characters"]:
        key = normalise_name(entry.name)
        is_new = limit is None and key not in live_ids and key not in hoyowiki.NOT_CHARACTERS
        if not is_new and limit is not None and sampled >= limit:
            continue
        sampled += 1
        page = wiki.page(entry.entry_id)
        if is_new:
            character = hoyowiki.announced_character(entry, page, now)
            if character is None:
                official.skipped_beta.append(entry.name)
                continue
            if hoyowiki.page_has_kit(page):
                log.info("%s: official kit modules present (not ingested yet)", entry.name)
            official.announced.append(character)
            live_ids[key] = character.id
        entity_id = live_ids.get(key, f"character/{slugify(entry.name)}")
        official.videos += hoyowiki.parse_videos(page, entity_id, now)
    return official


def build(
    out: Path,
    cache: Path | None,
    limit: int | None,
    blocklist: set[str],
    sources: tuple[str, ...] = SOURCES,
) -> dict:
    now = datetime.now(UTC)
    take = (lambda it: itertools.islice(it, limit)) if limit else (lambda it: it)
    fetched: dict[str, list] = {}
    source_info: dict[str, dict] = {}
    official = Official({}, [], [], [])
    yatta: YattaSource | None = None
    schedule: list[dict] = []

    if "yatta" in sources:
        client = PoliteClient(cache_dir=cache)
        yatta = YattaSource(client)
        try:
            version = yatta.game_version()
            log.info("Yatta live data version: %s", version)
            fetched = {
                "characters": list(take(yatta.characters(now, version))),
                "weapons": list(take(yatta.weapons(now, version))),
                "artifact_sets": list(take(yatta.artifact_sets(now, version))),
            }
            schedule = parse_schedule(yatta.daily_schedule())
            source_info["yatta"] = {"game_version": version}
        finally:
            client.close()

    # HoYoWiki confirms Yatta's records, so it only runs alongside Yatta.
    if "hoyowiki" in sources and fetched:
        wiki_client = PoliteClient(cache_dir=cache, headers=hoyowiki.HEADERS)
        try:
            official = fetch_official(
                hoyowiki.HoYoWikiSource(wiki_client), fetched["characters"], now, limit
            )
        finally:
            wiki_client.close()
        fetched["characters"] += official.announced
        source_info["hoyowiki"] = {"official_names": {k: len(v) for k, v in official.names.items()}}
        log.info(
            "HoYoWiki: %s official names, %d announced, %d videos",
            source_info["hoyowiki"]["official_names"],
            len(official.announced),
            len(official.videos),
        )

    out.mkdir(parents=True, exist_ok=True)
    renderers = {
        "characters": character_docs,
        "weapons": weapon_docs,
        "artifact_sets": artifact_docs,
    }
    docs, dropped, unverified, counts = [], [], [], {}
    kept: dict[str, list] = {}
    for kind, records in fetched.items():
        # Only full builds with HoYoWiki may drop undated records it does not list.
        names = official.names.get(kind) if limit is None and official.names else None
        report = gate(records, now, blocklist, official_names=names)
        kept[kind] = report.kept
        _write_jsonl(out / f"{kind}.jsonl", report.kept)
        for record in report.kept:
            docs.extend(renderers[kind](record))
        dropped += report.dropped
        unverified += report.unverified
        counts[kind] = {"fetched": len(records), "kept": len(report.kept)}
    if official.names:
        counts["announced"] = [c.name for c in official.announced]
        counts["videos"] = len(official.videos)

    if "kqm" in sources:
        kqm = KqmSource(cache_dir=cache)
        try:
            sha = kqm.fetch()
            log.info("KQM TCL commit: %s", sha)
            pages = list(take(kqm.pages(now, blocklist)))
        finally:
            kqm.close()
        # KQM pages carry no release data: only serve character pages for characters
        # that are *released* according to official data in this same build.
        released = (
            {c.id for c in kept.get("characters", []) if c.release.status == ReleaseStatus.RELEASED}
            if "yatta" in sources and not limit
            else None
        )
        kqm_docs, linked_drops, linked_unverified = gate_linked_docs(
            [d for _, page in pages for d in page.docs], released
        )
        docs += kqm_docs
        dropped += [drop for _, page in pages for drop in page.dropped] + linked_drops
        unverified += linked_unverified
        counts["kqm"] = {"pages": len(pages), "docs": len(kqm_docs)}
        source_info["kqm"] = {"game_version": sha, "license": "CC BY-NC-SA 4.0"}

    if yatta is not None:
        # Only records the gate kept reach the planner; it skips announced characters itself.
        planner = build_planner(
            kept.get("characters", []),
            yatta.character_materials,
            kept.get("weapons", []),
            yatta.weapon_materials,
            schedule,
            source_info["yatta"]["game_version"],
            now.isoformat(),
        )
        (out / "planner.json").write_text(
            json.dumps(planner, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        counts["planner"] = {
            "characters": len(planner["characters"]),
            "weapons": len(planner["weapons"]),
        }

    # Newer reactions are defined across many kits: compile each into one guide (no model).
    guides = reaction_guides(docs, now)
    docs += guides
    counts["reaction_guides"] = len(guides)

    check_unique_ids(docs)
    _write_jsonl(out / "docs.jsonl", docs)
    _write_jsonl(out / "videos.jsonl", official.videos)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "built_at": now.isoformat(),
        "sources": source_info,
        "counts": counts,
        "docs": len(docs),
        "doc_hashes": {d.doc_id: d.content_hash for d in docs},
        "dropped": [{"id": i, "reason": r} for i, r in dropped],
        "unverified": unverified,
        "skipped_beta": official.skipped_beta,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("data/build"))
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
        help="optional HTTP cache dir (use in dev to avoid re-fetching)",
    )
    parser.add_argument("--limit", type=int, default=None, help="max items per type (dev)")
    parser.add_argument("--blocklist", type=Path, default=Path("config/blocklist.txt"))
    parser.add_argument(
        "--sources",
        type=lambda s: tuple(x.strip() for x in s.split(",") if x.strip()),
        default=SOURCES,
        help=f"comma-separated subset of {','.join(SOURCES)} (default: all)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    blocklist: set[str] = set()
    if args.blocklist.exists():
        blocklist = {
            line.strip()
            for line in args.blocklist.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
    if unknown := set(args.sources) - set(SOURCES):
        parser.error(f"unknown sources: {', '.join(sorted(unknown))}")
    manifest = build(args.out, args.cache, args.limit, blocklist, args.sources)
    log.info(
        "counts=%s docs=%d dropped=%d unverified=%d",
        manifest["counts"],
        manifest["docs"],
        len(manifest["dropped"]),
        len(manifest["unverified"]),
    )


if __name__ == "__main__":
    main()
