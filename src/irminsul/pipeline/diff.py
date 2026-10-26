"""Compare two corpus manifests: a human-readable changelog plus safety guards.

Usage:
    uv run irminsul-diff --old prev/manifest.json --new data/build/manifest.json \
        --out changelog.md [--max-drop 0.10]

Exit code 1 if a guard trips (e.g. a source silently lost >10% of its records), so the
weekly job fails loudly instead of publishing a broken corpus.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

GUARDED = ("characters", "weapons", "artifact_sets", "kqm")


@dataclass
class CorpusDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    counts: dict[str, tuple[int, int]] = field(default_factory=dict)  # kind -> (old, new)
    versions: dict[str, tuple[str | None, str | None]] = field(default_factory=dict)
    announced: tuple[list[str], list[str]] = ([], [])
    new_drops: list[dict] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed or self.new_drops)


def _kept(manifest: dict, kind: str) -> int:
    value = manifest.get("counts", {}).get(kind) or {}
    return int(value.get("kept", value.get("docs", 0)))


def compare(old: dict, new: dict) -> CorpusDiff:
    old_h, new_h = old.get("doc_hashes", {}), new.get("doc_hashes", {})
    d = CorpusDiff(
        added=sorted(new_h.keys() - old_h.keys()),
        removed=sorted(old_h.keys() - new_h.keys()),
        changed=sorted(k for k in new_h.keys() & old_h.keys() if new_h[k] != old_h[k]),
    )
    for kind in GUARDED:
        if kind in old.get("counts", {}) or kind in new.get("counts", {}):
            d.counts[kind] = (_kept(old, kind), _kept(new, kind))
    for source in sorted(set(old.get("sources", {})) | set(new.get("sources", {}))):
        before = old.get("sources", {}).get(source, {}).get("game_version")
        after = new.get("sources", {}).get(source, {}).get("game_version")
        if before != after:
            d.versions[source] = (before, after)
    d.announced = (
        old.get("counts", {}).get("announced", []),
        new.get("counts", {}).get("announced", []),
    )
    old_drops = {x["id"] for x in old.get("dropped", [])}
    d.new_drops = [x for x in new.get("dropped", []) if x["id"] not in old_drops]
    return d


def guard(old: dict, new: dict, max_drop: float = 0.10) -> list[str]:
    """Reasons to refuse publishing this build."""
    problems = []
    for kind in GUARDED:
        before, after = _kept(old, kind), _kept(new, kind)
        if before and after < before * (1 - max_drop):
            problems.append(f"{kind}: {before} -> {after} (more than {max_drop:.0%} lost)")
    if new.get("unverified"):
        problems.append(f"{len(new['unverified'])} records are unverified by official sources")
    if old and new.get("docs", 0) < old.get("docs", 0) * (1 - max_drop):
        problems.append(f"total docs {old.get('docs')} -> {new.get('docs')}")
    return problems


def _ids(title: str, ids: list[str], limit: int = 25) -> list[str]:
    if not ids:
        return []
    lines = [f"**{title} ({len(ids)})**"] + [f"- `{i}`" for i in ids[:limit]]
    if len(ids) > limit:
        lines.append(f"- ... and {len(ids) - limit} more")
    return lines + [""]


def to_markdown(diff: CorpusDiff, new: dict, problems: list[str]) -> str:
    lines = [f"## Corpus update {new.get('built_at', '')[:10]}", ""]
    if problems:
        lines += ["**Guard failures (not publishable):**"] + [f"- {p}" for p in problems] + [""]
    if diff.versions:
        lines += ["| Source | Before | After |", "|---|---|---|"]
        lines += [f"| {s} | {a or '-'} | {b or '-'} |" for s, (a, b) in diff.versions.items()]
        lines.append("")
    lines += ["| Records | Before | After |", "|---|---|---|"]
    lines += [f"| {k} | {a} | {b} |" for k, (a, b) in diff.counts.items()]
    lines.append("")
    before, after = diff.announced
    if before != after:
        lines += [
            f"**Announced (official, not yet released):** {', '.join(after) or 'none'}"
            + (f" (was: {', '.join(before) or 'none'})" if before else ""),
            "",
        ]
    if diff.is_empty:
        lines.append("No content changes.")
    lines += _ids("Added docs", diff.added) + _ids("Removed docs", diff.removed)
    lines += _ids("Changed docs", diff.changed)
    if diff.new_drops:
        lines += [f"**Newly dropped by the leak gate ({len(diff.new_drops)})**"]
        lines += [f"- `{x['id']}`: {x['reason']}" for x in diff.new_drops[:25]] + [""]
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--old", type=Path, help="previous manifest (omit for a first build)")
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--max-drop", type=float, default=0.10)
    args = parser.parse_args()
    old = json.loads(args.old.read_text(encoding="utf-8")) if args.old and args.old.exists() else {}
    new = json.loads(args.new.read_text(encoding="utf-8"))
    problems = guard(old, new, args.max_drop)
    text = to_markdown(compare(old, new), new, problems)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
