"""Build the corpus: fetch sources -> leak gate -> render docs -> write a versioned snapshot.

Usage:
    uv run irminsul-build --out data/build --cache data/cache
    uv run irminsul-build --limit 5     # quick dev run on a few items per type
"""

import argparse
import itertools
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from irminsul.pipeline.gate import gate, normalise_name
from irminsul.pipeline.render import artifact_docs, character_docs, weapon_docs
from irminsul.schema import SCHEMA_VERSION, Character, Video, slugify
from irminsul.sources import hoyowiki
from irminsul.sources.http import PoliteClient
from irminsul.sources.yatta import YattaSource

log = logging.getLogger("irminsul.build")


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


def build(out: Path, cache: Path | None, limit: int | None, blocklist: set[str]) -> dict:
    now = datetime.now(UTC)
    client = PoliteClient(cache_dir=cache)
    yatta = YattaSource(client)
    try:
        version = yatta.game_version()
        log.info("Yatta live data version: %s", version)
        take = (lambda it: itertools.islice(it, limit)) if limit else (lambda it: it)
        fetched = {
            "characters": list(take(yatta.characters(now, version))),
            "weapons": list(take(yatta.weapons(now, version))),
            "artifact_sets": list(take(yatta.artifact_sets(now, version))),
        }
    finally:
        client.close()

    wiki_client = PoliteClient(cache_dir=cache, headers=hoyowiki.HEADERS)
    try:
        official = fetch_official(
            hoyowiki.HoYoWikiSource(wiki_client), fetched["characters"], now, limit
        )
    finally:
        wiki_client.close()
    fetched["characters"] += official.announced
    log.info(
        "HoYoWiki: %s official names, %d announced, %d videos",
        {k: len(v) for k, v in official.names.items()},
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
    for kind, records in fetched.items():
        # Partial builds only fetch a slice of the official lists' counterparts, so only
        # full builds may drop undated records that HoYoWiki does not list.
        names = official.names.get(kind) if limit is None else None
        report = gate(records, now, blocklist, official_names=names)
        _write_jsonl(out / f"{kind}.jsonl", report.kept)
        for record in report.kept:
            docs.extend(renderers[kind](record))
        dropped += report.dropped
        unverified += report.unverified
        counts[kind] = {"fetched": len(records), "kept": len(report.kept)}
    counts["announced"] = [c.name for c in official.announced]
    counts["videos"] = len(official.videos)
    check_unique_ids(docs)
    _write_jsonl(out / "docs.jsonl", docs)
    _write_jsonl(out / "videos.jsonl", official.videos)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "built_at": now.isoformat(),
        "sources": {
            "yatta": {"game_version": version},
            "hoyowiki": {"official_names": {k: len(v) for k, v in official.names.items()}},
        },
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
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    blocklist: set[str] = set()
    if args.blocklist.exists():
        blocklist = {
            line.strip()
            for line in args.blocklist.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
    manifest = build(args.out, args.cache, args.limit, blocklist)
    log.info(
        "counts=%s docs=%d dropped=%d unverified=%d",
        manifest["counts"],
        manifest["docs"],
        len(manifest["dropped"]),
        len(manifest["unverified"]),
    )


if __name__ == "__main__":
    main()
