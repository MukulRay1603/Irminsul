"""Builds for characters the team hasn't written up yet, read from KQM's quick guides.

The guides list their picks in tables, one item per row, so this needs no model: it reads
the names in the guide's own order and keeps only names that exist in official data.
Nothing here can invent an item. What it publishes is a short list of names and stats with a
link to the guide, marked as read by machine, never the guide's prose.

keqingmains.com's robots.txt allows crawling; this asks for one page per character, weekly.
"""

import html
import logging
import re
from dataclasses import dataclass, field

from irminsul.pipeline.gate import normalise_name
from irminsul.schema import slugify
from irminsul.sources.http import FetchError, PoliteClient

log = logging.getLogger(__name__)

GUIDE = "https://keqingmains.com/q/{}-quickguide/"
_HEADING = re.compile(r"<h([1-4])[^>]*>(.*?)</h\1>", re.S)
_TAG = re.compile(r"<[^>]+>")
_NAME_NOISE = re.compile(r"^\s*(?:\d\s*★|\d\s*pc)\s*|\s*\([^)]*\)\s*$", re.I)
_ALTERNATIVES = re.compile(r"\s+[/+]\s+|\s+or\s+", re.I)
_MODIFIED = re.compile(r"article:modified_time\" content=\"([^\"]+)\"")
_PRIORITY = re.compile(r"Stat Priority:\s*</strong>(.*?)</p>", re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)


def _text(fragment: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", fragment)).split())


def _section(page: str, title: str) -> str:
    """A section's HTML: from its heading to the next heading of the same or a higher level."""
    headings = list(_HEADING.finditer(page))
    for i, h in enumerate(headings):
        if _text(h.group(2)).lower() != title.lower():
            continue
        for later in headings[i + 1 :]:
            if int(later.group(1)) <= int(h.group(1)):
                return page[h.end() : later.start()]
        return page[h.end() :]
    return ""


def _picks(section: str, known: set[str]) -> list[str]:
    """Names in guide order. A pick is a table row whose first cell is an item's name, and only
    names official data has are kept, so prose and typos can't get in."""
    out: list[str] = []
    for row in _ROW.findall(section):
        cell = _CELL.search(row)
        for raw in _ALTERNATIVES.split(_text(cell.group(1))) if cell else []:
            name = _NAME_NOISE.sub("", _NAME_NOISE.sub("", raw)).strip()
            if normalise_name(name) in known and name not in out:
                out.append(name)
    return out


def _main_stats(section: str) -> str | None:
    rows = [[_text(c) for c in _CELL.findall(r)] for r in _ROW.findall(section)]
    for head, values in zip(rows, rows[1:], strict=False):
        if [h.lower() for h in head] == ["sands", "goblet", "circlet"] and len(values) == 3:
            return f"Sands {values[0]}; Goblet {values[1]}; Circlet {values[2]}"
    return None


@dataclass
class GuideBuild:
    url: str
    modified: str | None = None  # ISO date the guide last changed
    weapons: list[str] = field(default_factory=list)
    sets: list[str] = field(default_factory=list)
    main_stats: str | None = None
    priority: str | None = None

    def lines(self, version: str, today: str) -> list[str]:
        """As fact lines (see team_facts.py). No weapons and no sets means nothing to say."""
        facts = []
        if self.weapons:
            facts.append(
                f"KQM's quick guide lists these weapons, in order: {', '.join(self.weapons)}"
            )
        if self.sets:
            facts.append(
                f"KQM's quick guide lists these artifact sets, in order: {', '.join(self.sets)}"
            )
        if facts and self.main_stats:
            facts.append(f"KQM's quick guide main stats: {self.main_stats}")
        if facts and self.priority:
            facts.append(f"KQM's quick guide substat priority: {self.priority}")
        return [f"- {fact} | {self.url} | {today} | {version}" for fact in facts]


def read_guide(page: str, url: str, weapons: set[str], sets: set[str]) -> GuideBuild:
    """`weapons` and `sets` are the normalised official names."""
    build = GuideBuild(url)
    if m := _MODIFIED.search(page):
        build.modified = m.group(1)[:10]
    build.weapons = _picks(_section(page, "Weapons"), weapons)
    artifacts = _section(page, "Artifact Sets") or _section(page, "Artifacts")
    build.sets = _picks(artifacts, sets)
    stats = _section(page, "Artifact Stats") or artifacts
    build.main_stats = _main_stats(stats)
    if m := _PRIORITY.search(stats):
        build.priority = _text(m.group(1))
    return build


def guide_urls(name: str) -> list[str]:
    """Where a character's quick guide should be: full name first, then the given name."""
    slug = slugify(name)
    urls = [GUIDE.format(slug)]
    if "-" in slug:
        urls.append(GUIDE.format(slug.rsplit("-", 1)[1]))
    return urls


def fetch_guide(
    client: PoliteClient, urls: list[str], weapons: set[str], sets: set[str]
) -> GuideBuild | None:
    """The first of `urls` that exists. Raises FetchError if the site can't be reached."""
    for url in urls:
        page = client.get_page(url)
        if page is not None:
            return read_guide(page, url, weapons, sets)
    return None


__all__ = ["FetchError", "GuideBuild", "fetch_guide", "guide_urls", "read_guide"]
