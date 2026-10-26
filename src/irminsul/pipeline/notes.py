"""Build the local-only `rayy_verified` docs from the team's research notes.

Usage:
    uv run irminsul-notes --notes-dir "F:/Genshin Edits/Assets/Notes/Research" --out data/build

Writes `docs_rayy.jsonl` and `manifest_rayy.json` next to the main build output. These
files are not published: the notes are private team documents until Ray approves.
"""

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from irminsul.sources.rayy_notes import ingest, load_allowlist

log = logging.getLogger("irminsul.notes")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notes-dir", type=Path, required=True)
    parser.add_argument("--allowlist", type=Path, default=Path("config/rayy_notes_allowlist.txt"))
    parser.add_argument("--out", type=Path, default=Path("data/build"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    now = datetime.now(UTC)
    results = ingest(args.notes_dir, load_allowlist(args.allowlist), now)
    docs = [d for r in results.values() for d in r.docs]
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "docs_rayy.jsonl").open("w", encoding="utf-8") as f:
        for doc in docs:
            f.write(doc.model_dump_json() + "\n")
    manifest = {
        "built_at": now.isoformat(),
        "published": False,
        "files": {
            name: {
                "docs": len(r.docs),
                "kept_lines": r.kept_lines,
                "dropped_lines": r.dropped_lines,
            }
            for name, r in results.items()
        },
        "docs": len(docs),
    }
    (args.out / "manifest_rayy.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("rayy notes: %d docs from %d files", len(docs), len(results))


if __name__ == "__main__":
    main()
