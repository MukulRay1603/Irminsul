"""KQM Theorycrafting Library (TCL) via a shallow clone of github.com/KQM-git/TCL.

TCL is a Docusaurus site: Markdown with MDX imports and JSX components under `docs/`.
It documents released content only, so pages are marked RELEASED; any page or section
whose title or frontmatter mentions beta, leaks or unreleased content is dropped anyway.
The pinned commit SHA is recorded as `game_version` so every citation is reproducible.
Parsing is kept in pure functions so it can be tested against saved fixtures.
"""

import logging
import re
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from irminsul.schema import Doc, Release, ReleaseStatus, SourceRef, Tier, slugify

log = logging.getLogger(__name__)

REPO = "https://github.com/KQM-git/TCL"
BRANCH = "master"
FOLDERS = (
    "characters",
    "equipment",
    "general-mechanics",
    "combat-mechanics",
    "enemy-data",
    "resources",
)

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_IMPORT = re.compile(
    r"^\s*(import\s.+\sfrom\s+['\"].+['\"]|import\s+['\"].+['\"]|export\s.+);?\s*$"
)
_HTML_TAG = re.compile(
    r"</?(?:div|span|p|blockquote|details|summary|img|br|hr|u|b|i|em|strong|sup|sub|small|"
    r"center|iframe|table|thead|tbody|tr|td|th|a|ul|ol|li)\b[^<>]*/?>",
    re.IGNORECASE,
)
_ADMONITION = re.compile(r"^:::\s*(\w+)?\s*(.*)$")
_FRONTMATTER_REF = re.compile(r"\{frontMatter\.(\w+)\}")
_FENCE = re.compile(r"^\s*(```|~~~)")
_TAB_LABEL = re.compile(r"<TabItem\b.*?\blabel=['\"]([^'\"]+)['\"]", re.DOTALL)
_LEAKY = re.compile(r"\b(beta|leaks?|leaked|unreleased)\b", re.IGNORECASE)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split simple `key: value` YAML frontmatter from the body."""
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not key.startswith((" ", "\t", "-")):
            meta[key.strip()] = value.strip().strip("'\"")
    return meta, text[m.end() :]


def _strip_components(text: str) -> str:
    """Remove JSX component tags (<Tabs ...>, </TabItem>, <Skill ... />), keeping inner text.

    A <TabItem label="..."> becomes a `###` heading so tab context survives.

    Attributes can hold `{...}` expressions spanning lines, so this scans with brace and
    quote tracking instead of a regex.
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        j = i + 2 if text.startswith("</", i) else i + 1
        if text[i] == "<" and j < n and text[j].isupper():
            depth, quote, k = 0, "", j
            while k < n:
                ch = text[k]
                if quote:
                    quote = "" if ch == quote else quote
                elif ch in "'\"`":
                    quote = ch
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                elif ch == ">" and depth <= 0:
                    break
                k += 1
            if k < n:  # an unterminated `<X` is prose, not a tag
                if tab := _TAB_LABEL.match(text, i, k + 1):
                    out.append(f"\n### {tab.group(1)}\n")
                i = k + 1
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def strip_mdx(text: str, meta: dict[str, str] | None = None) -> str:
    """Turn TCL MDX into plain Markdown. Fenced code blocks are left untouched."""
    meta = meta or {}
    text = _COMMENT.sub("", text)
    parts: list[str] = []
    prose: list[str] = []

    def flush() -> None:
        if not prose:
            return
        chunk = "\n".join(line for line in prose if not _IMPORT.match(line))
        chunk = _FRONTMATTER_REF.sub(lambda m: meta.get(m.group(1), ""), chunk)
        chunk = _strip_components(chunk)
        chunk = _HTML_TAG.sub(lambda m: " " if m.group(0).lower().startswith("<br") else "", chunk)
        lines = []
        for line in chunk.splitlines():
            if am := _ADMONITION.match(line.strip()):
                line = am.group(2) or (am.group(1) or "").title()
                if not line:
                    continue
            lines.append(line.rstrip())
        parts.append("\n".join(lines))
        prose.clear()

    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            if not in_fence:
                flush()
            in_fence = not in_fence
            parts.append(line)
        elif in_fence:
            parts.append(line)
        else:
            prose.append(line)
    flush()
    text = "\n".join(parts)
    text = re.sub(r"\n[ \t]*(\n[ \t]*)+\n", "\n\n", text)
    return text.strip()


@dataclass
class Section:
    heading: str | None  # None for the text before the first `##`
    body: str


def split_sections(text: str) -> tuple[str | None, list[Section]]:
    """Return the page `#` title and its `##` sections (code fences are not split)."""
    title = None
    sections = [Section(None, "")]
    body: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        if not in_fence and line.startswith("# ") and title is None:
            title = line[2:].strip()
            continue
        if not in_fence and line.startswith("## "):
            sections[-1].body = "\n".join(body).strip()
            sections.append(Section(line[3:].strip(), ""))
            body = []
            continue
        body.append(line)
    sections[-1].body = "\n".join(body).strip()
    return title, sections


def page_id(rel: Path) -> str:
    """Stable id from the path under docs/. Character pages drop the element folder."""
    parts = list(rel.with_suffix("").parts)
    if parts[-1].lower() == "readme":
        parts.pop()
    if parts[0] == "characters" and len(parts) == 3:
        parts = [parts[0], parts[2]]
    return "kqm/" + "/".join(slugify(p) for p in parts)


def _has_content(body: str) -> bool:
    return any(line.strip() and not line.lstrip().startswith("#") for line in body.splitlines())


@dataclass
class PageResult:
    docs: list[Doc] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)  # (id, reason)


def parse_page(
    raw: str, rel: Path, sha: str, fetched_at: datetime, blocklist: set[str] | None = None
) -> PageResult:
    """Render one TCL file (`rel` is relative to docs/) into one Doc per `##` section.

    Every section becomes its own Doc so ids never depend on file length.
    """
    result = PageResult()
    pid = page_id(rel)
    meta, body = parse_frontmatter(raw)
    title, sections = split_sections(strip_mdx(body, meta))
    title = title or meta.get("title") or rel.stem.replace("-", " ").title()

    leaky = [v for v in [title, *meta.values()] if _LEAKY.search(v)]
    if leaky:
        result.dropped.append((pid, f"mentions beta/leak/unreleased: {leaky[0]!r}"))
        return result

    entity_id = None
    if rel.parts[0] == "characters" and len(rel.parts) == 3:
        entity_id = f"character/{slugify(title)}"
        if entity_id in (blocklist or set()):
            result.dropped.append((pid, "blocklisted"))
            return result

    source = SourceRef(
        source="kqm",
        url=f"{REPO}/blob/{sha}/docs/{rel.as_posix()}",
        tier=Tier.KQM,
        fetched_at=fetched_at,
        game_version=sha,
    )
    seen: dict[str, int] = {}
    for section in sections:
        slug = slugify(section.heading) if section.heading else "intro"
        seen[slug] = seen.get(slug, 0) + 1
        if seen[slug] > 1:
            slug = f"{slug}-{seen[slug]}"
        doc_id = f"{pid}#{slug}"
        headings = [section.heading or ""]
        headings += [
            line.lstrip("#").strip() for line in section.body.splitlines() if line[:1] == "#"
        ]
        if leak := next((h for h in headings if _LEAKY.search(h)), None):
            result.dropped.append((doc_id, f"mentions beta/leak/unreleased: {leak!r}"))
            continue
        if not _has_content(section.body):
            continue
        heading = f"\n## {section.heading}" if section.heading else ""
        result.docs.append(
            Doc(
                doc_id=doc_id,
                entity_id=entity_id,
                kind=f"kqm_{rel.parts[0].replace('-', '_')}",
                title=f"{title}: {section.heading}" if section.heading else title,
                text=f"# {title}{heading}\n{section.body}",
                release=Release(status=ReleaseStatus.RELEASED),
                source=source,
            )
        )
    return result


def iter_pages(docs_dir: Path) -> Iterator[Path]:
    """TCL pages under the copied folders, skipping templates and `_partials`."""
    for folder in FOLDERS:
        for path in sorted((docs_dir / folder).rglob("*.md*")):
            rel = path.relative_to(docs_dir)
            if path.suffix not in (".md", ".mdx") or any(p.startswith("_") for p in rel.parts):
                continue
            yield rel


class KqmSource:
    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir
        self._tmp: tempfile.TemporaryDirectory | None = None
        self.sha: str | None = None
        self.checkout: Path | None = None

    def fetch(self) -> str:
        """Shallow-clone (or refresh) TCL and return the checked-out commit SHA."""
        if self.cache_dir:
            dest = self.cache_dir / "kqm-tcl"
        else:
            self._tmp = tempfile.TemporaryDirectory(prefix="irminsul-tcl-")
            dest = Path(self._tmp.name) / "tcl"
        if (dest / ".git").exists():
            _git("fetch", "--depth", "1", "origin", BRANCH, cwd=dest)
            _git("checkout", "--force", "--detach", "FETCH_HEAD", cwd=dest)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            _git("clone", "--depth", "1", "--branch", BRANCH, REPO + ".git", str(dest))
        self.checkout = dest
        self.sha = _git("rev-parse", "HEAD", cwd=dest)
        return self.sha

    def pages(
        self, fetched_at: datetime, blocklist: set[str] | None = None
    ) -> Iterator[tuple[Path, PageResult]]:
        if self.checkout is None or self.sha is None:
            raise RuntimeError("call fetch() first")
        docs_dir = self.checkout / "docs"
        for rel in iter_pages(docs_dir):
            try:
                raw = (docs_dir / rel).read_text(encoding="utf-8")
                yield rel, parse_page(raw, rel, self.sha, fetched_at, blocklist)
            except Exception:
                log.exception("failed to parse TCL page %s", rel)

    def close(self) -> None:
        if self._tmp:
            self._tmp.cleanup()


def _git(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return proc.stdout.strip()
