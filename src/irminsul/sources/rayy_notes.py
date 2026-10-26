"""RAYY team research notes: fact-checked claims as the `rayy_verified` tier.

The notes are working documents for videos, so ingestion is deliberately narrow:
- only files on an explicit allowlist are opened (the notes folder is never listed),
- any file whose name mentions "leak" is refused, even if allowlisted,
- only lines carrying an accepted tag ([OFFICIAL], [KQM], CONFIRMED) are kept,
- a line is dropped if it also carries an uncertainty tag ([OPINION], [VERIFY],
  [DATAMINED], [COMMUNITY], DATA-DERIVED, COMMUNITY THEORY, MY MATH) or mentions leaks,
- legend, source-list and production sections (scripts, hooks, VO) are skipped.

One Doc per `##` section that still has kept lines. The notes live on Ray's PC, so this
source runs locally only and its output is not published without Ray's approval.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from irminsul.schema import Doc, Release, ReleaseStatus, SourceRef, Tier, slugify

ACCEPT = re.compile(r"\[(?:OFFICIAL|KQM)\b[^\]]*\]|\bCONFIRMED\b")
REJECT = re.compile(
    r"\[(?:OPINION|VERIFY|DATAMINED|COMMUNITY)\b[^\]]*\]"
    r"|\bDATA-DERIVED\b|\bCOMMUNITY THEORY\b|\bMY MATH\b"
    r"|\bleak(?:s|ed)?\b|\bdatamin(?:e|ed|ing)\b|\bbeta\b",
    re.IGNORECASE,
)
SKIP_SECTION = re.compile(
    r"how to read|^tags?\b|\bsources?\b|method|limits|script|hook|\bvo\b|voice.?over|thumbnail|"
    r"b-?roll|on.?screen|fixes|verdict",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://[^\s)\]>|]+")
_VERSION = re.compile(r"\b(?:version|game|live(?: game)?)\s*(\d\.\d)\b", re.IGNORECASE)


@dataclass
class NoteResult:
    docs: list[Doc] = field(default_factory=list)
    kept_lines: int = 0
    dropped_lines: int = 0


def load_allowlist(path: Path) -> list[str]:
    """One file name per line; '#' starts a comment."""
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line)
    return names


def is_refused(name: str) -> bool:
    return "leak" in name.lower()


# Lines that define the tags rather than state a fact: "[OFFICIAL] = ...", "Legend: ...".
_LEGEND = re.compile(
    r"^[\s|*-]*\[?(?:OFFICIAL|KQM|CONFIRMED)\b[^\]]*\]?\**\s*[=|]|^\s*legend\b|unless tagged",
    re.IGNORECASE,
)


def keep_line(line: str) -> bool:
    return bool(ACCEPT.search(line)) and not REJECT.search(line) and not _LEGEND.search(line)


def _is_separator(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and set(stripped) <= set("|-: ")


def detect_version(text: str) -> str | None:
    m = _VERSION.search(text[:2000])
    return m.group(1) if m else None


def parse_note(text: str, file_name: str, fetched_at: datetime) -> NoteResult:
    result = NoteResult()
    stem = slugify(Path(file_name).stem)
    version = detect_version(text)
    title = next(
        (line[2:].strip() for line in text.splitlines() if line.startswith("# ")), file_name
    )

    sections: list[tuple[str, list[str]]] = [("Overview", [])]
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif not line.startswith("# "):
            sections[-1][1].append(line)

    seen: dict[str, int] = {}
    for heading, lines in sections:
        if SKIP_SECTION.search(heading):
            continue
        kept: list[str] = []
        subheading = None
        table_header: str | None = None  # header row of the current table, until emitted
        for i, line in enumerate(lines):
            if line.startswith("#"):
                subheading = line.lstrip("#").strip()
                continue
            if not line.strip().startswith("|"):
                table_header = None
            elif i + 1 < len(lines) and _is_separator(lines[i + 1]):
                table_header = line.rstrip()
                continue
            if not line.strip() or _is_separator(line):
                continue
            if keep_line(line):
                if subheading and SKIP_SECTION.search(subheading):
                    result.dropped_lines += 1
                    continue
                if subheading:
                    kept.append(f"\n### {subheading}")
                    subheading = None
                if table_header:  # keep column context for table rows
                    kept += [table_header, "|" + "---|" * (table_header.count("|") - 1)]
                    table_header = None
                kept.append(line.rstrip())
                result.kept_lines += 1
            elif ACCEPT.search(line) or REJECT.search(line):
                result.dropped_lines += 1
        if not any(not k.startswith("\n###") for k in kept):
            continue
        slug = slugify(heading) or "section"
        seen[slug] = seen.get(slug, 0) + 1
        if seen[slug] > 1:
            slug = f"{slug}-{seen[slug]}"
        body = "\n".join(kept).strip()
        refs = sorted(set(_URL.findall(body)))
        result.docs.append(
            Doc(
                doc_id=f"rayy/{stem}#{slug}",
                entity_id=None,
                kind="rayy_note",
                title=f"{title}: {heading}",
                text=f"# {title}\n## {heading}\n{body}",
                release=Release(status=ReleaseStatus.RELEASED),
                source=SourceRef(
                    source="rayy_notes",
                    url=f"rayy-notes:{stem}#{slug}",
                    tier=Tier.RAYY_VERIFIED,
                    fetched_at=fetched_at,
                    game_version=version,
                    refs=refs,
                ),
            )
        )
    return result


def ingest(notes_dir: Path, allowlist: list[str], fetched_at: datetime) -> dict[str, NoteResult]:
    """Parse only the allowlisted files. Refused or missing files raise immediately."""
    results: dict[str, NoteResult] = {}
    for name in allowlist:
        if is_refused(name) or Path(name).name != name:
            raise ValueError(f"refusing note file {name!r}")
        path = notes_dir / name
        results[name] = parse_note(path.read_text(encoding="utf-8"), name, fetched_at)
    return results
