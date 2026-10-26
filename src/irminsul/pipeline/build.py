"""Build the corpus: fetch sources -> leak gate -> render docs -> write a versioned snapshot.

Usage:
    uv run irminsul-build --out data/build --cache data/cache
    uv run irminsul-build --limit 5     # quick dev run on a few items per type
"""

import argparse
import itertools
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from irminsul.pipeline.gate import gate
from irminsul.pipeline.render import artifact_docs, character_docs, weapon_docs
from irminsul.schema import SCHEMA_VERSION
from irminsul.sources.http import PoliteClient
from irminsul.sources.yatta import YattaSource

log = logging.getLogger("irminsul.build")


def _write_jsonl(path: Path, rows: list[BaseModel]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(row.model_dump_json() + "\n")


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

    out.mkdir(parents=True, exist_ok=True)
    renderers = {
        "characters": character_docs,
        "weapons": weapon_docs,
        "artifact_sets": artifact_docs,
    }
    docs, dropped, unverified, counts = [], [], [], {}
    for kind, records in fetched.items():
        report = gate(records, now, blocklist)
        _write_jsonl(out / f"{kind}.jsonl", report.kept)
        for record in report.kept:
            docs.extend(renderers[kind](record))
        dropped += report.dropped
        unverified += report.unverified
        counts[kind] = {"fetched": len(records), "kept": len(report.kept)}
    _write_jsonl(out / "docs.jsonl", docs)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "built_at": now.isoformat(),
        "sources": {"yatta": {"game_version": version}},
        "counts": counts,
        "docs": len(docs),
        "doc_hashes": {d.doc_id: d.content_hash for d in docs},
        "dropped": [{"id": i, "reason": r} for i, r in dropped],
        "unverified": unverified,
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
