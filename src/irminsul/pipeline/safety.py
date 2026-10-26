"""Publish gate for new content: the checks a person did on the review PR, automated.

A daily build that adds characters, weapons, sets, lore or announcements publishes on its own
when every check passes. If any check fails, the build is held for a person instead (review
PR plus an issue that says why). Checks:
1. Dates: every served character is released with no future release date, and announced
   characters have their official overview only (no kit docs).
2. Leak language: no added or changed doc mentions betas, leaks, datamines, leak sites, or a
   game version past the officially announced one.
3. Probes: the offline eval's leak, injection, off-topic, privacy, safety and spoiler probes
   all pass, and exact stat and passive answers stay at 100%.
4. Size: a build adding more than MAX_NEW_DOCS docs at once (a source suddenly dumping data)
   is held.
"""

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from irminsul.pipeline.diff import compare

MAX_NEW_DOCS = 400
STRICT_CATEGORIES = {
    "leak_probe",
    "injection",
    "offtopic",
    "privacy",
    "safety",
    "spoiler",
    "stat",
    "passive",
}
# Leak talk, not ordinary words: lore says "the news leaked" and items are called "Hakushin".
LEAK_LANGUAGE = re.compile(
    r"\bdatamin\w*|\bhakush\.in\b|\bhomdgcat\b|\btest server\b"
    r"|\bunreleased (character|kit|weapon|content|area|region)s?\b"
    r"|\bbeta (test\w*|server|version|kit|build)s?\b"
    r"|\bleak(s|ed)? (kit|character|banner|version|info\w*|content|drip|footage|images?)s?\b"
    r"|\b(according to|from|per) (the )?leaks?\b",
    re.I,
)
_VERSION = re.compile(r"\b(?:version|ver\.?|patch|v)\s?([4-9])\.(\d)\b", re.I)


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def check_dates(characters: list[dict], docs: list[dict], now: datetime) -> list[str]:
    problems = []
    announced = set()
    for c in characters:
        status = c["release"]["status"]
        if status == "announced":
            announced.add(c["id"])
            continue
        if status != "released":
            problems.append(f"{c['id']}: release status '{status}' is served")
            continue
        when = c["release"].get("released_at")
        if when and datetime.fromisoformat(when) > now:
            problems.append(f"{c['id']}: release date {when[:10]} is in the future")
    for d in docs:
        if d.get("entity_id") in announced and not d["doc_id"].endswith("#overview"):
            problems.append(f"{d['doc_id']}: kit detail for an announced (unreleased) character")
    return problems


def check_language(docs: list[dict], ids: set[str], announced: tuple[int, int]) -> list[str]:
    problems = []
    for d in docs:
        if d["doc_id"] not in ids:
            continue
        text = f"{d['title']}\n{d['text']}"
        if m := LEAK_LANGUAGE.search(text):
            problems.append(f"{d['doc_id']}: mentions '{m.group(0)}'")
        future = [v for v in _VERSION.findall(text) if (int(v[0]), int(v[1])) > announced]
        if future:
            problems.append(f"{d['doc_id']}: mentions version {'.'.join(future[0])}")
    return problems


def check_probes(report: dict) -> list[str]:
    return [
        f"eval {f['id']} ({f['category']}): {'; '.join(f['problems'])}"
        for f in report.get("failures", [])
        if f.get("category") in STRICT_CATEGORIES
    ]


def decide(old_manifest: dict, build: Path, now: datetime, report: dict | None) -> dict:
    new_manifest = json.loads((build / "manifest.json").read_text(encoding="utf-8"))
    diff = compare(old_manifest, new_manifest)
    docs = _jsonl(build / "docs.jsonl")
    live = new_manifest.get("sources", {}).get("yatta", {}).get("game_version") or "00"
    announced = (int(live[0]), int(live[1]) + 1) if live[:2].isdigit() else (9, 9)
    problems = check_dates(_jsonl(build / "characters.jsonl"), docs, now)
    problems += check_language(docs, set(diff.added) | set(diff.changed), announced)
    if report is not None:
        problems += check_probes(report)
    else:
        problems.append("offline eval did not run")
    if not old_manifest:
        problems.append("first publish: nothing to compare against")
    elif len(diff.added) > MAX_NEW_DOCS:
        problems.append(f"{len(diff.added)} new docs at once (limit {MAX_NEW_DOCS})")
    return {
        "auto_publish": not problems,
        "problems": problems[:50],
        "added": len(diff.added),
        "changed": len(diff.changed),
        "removed": len(diff.removed),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--old", type=Path, help="previously published manifest")
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--index", type=Path, default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    old = json.loads(args.old.read_text(encoding="utf-8")) if args.old and args.old.exists() else {}
    report = None
    try:  # offline answers: no model, no network
        from irminsul.engine.engine import Engine
        from irminsul.engine.entities import EntityStore
        from irminsul.engine.evaluate import evaluate
        from irminsul.engine.guards import GuardConfig, version_from_manifest

        manifest = json.loads((args.build / "manifest.json").read_text(encoding="utf-8"))
        live = version_from_manifest(
            manifest.get("sources", {}).get("yatta", {}).get("game_version")
        )
        cfg = GuardConfig(live, (live[0], live[1] + 1)) if live else GuardConfig()
        index = None
        if args.index:
            from irminsul.retrieval.index import HybridIndex

            index = HybridIndex.load(args.index)
        report = evaluate(Engine(EntityStore.load(args.build), index, None, cfg))
    except Exception as exc:  # the gate holds the build rather than crash the job
        print(f"offline eval failed: {exc}", file=sys.stderr)
    decision = decide(old, args.build, datetime.now(UTC), report)
    args.out.write_text(json.dumps(decision, indent=2), encoding="utf-8")
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()
