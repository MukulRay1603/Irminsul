"""Public RAYY team facts: short checked facts, each with its own source link.

Unlike the private notes (rayy_notes.py), this file was written for publishing: Ray approved
it, one fact per line, no names or opinions. Each line reads

    - <fact> | <source URL> | <date checked> | <game version it applies to>

under a `## <section>` heading. Facts sharing a section and a source become one Doc, so a
citation opens the page the fact came from. The tier follows the source: KQM pages are `kqm`
(the KQM switch drops them), wikis, guide sites and player posts are `community`, and lines
checked against official HoYoverse pages are `rayy_verified`.

A line is dropped if it is malformed, has no https source, mentions leaks or datamining,
looks like personal data, or applies to a version newer than the live game.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

from irminsul.engine.guards import has_personal_data
from irminsul.pipeline.safety import LEAK_LANGUAGE
from irminsul.schema import Doc, Release, ReleaseStatus, SourceRef, Tier, slugify

_SECTION = re.compile(r"^##\s+(?:\d+\.\s*)?(.+?)\s*$")
_FACT = re.compile(r"^-\s+(.+?)\s+\|\s+(\S+)\s+\|\s+(\d{4}-\d{2}-\d{2})\s+\|\s+(.+?)\s*$")
_VERSION = re.compile(r"\b(\d+)\.(\d+)\b")

KQM_HOSTS = ("keqingmains.com",)
OFFICIAL_HOSTS = ("hoyoverse.com", "wiki.hoyolab.com", "act.hoyolab.com")


@dataclass
class FactsResult:
    docs: list[Doc] = field(default_factory=list)
    kept_lines: int = 0
    dropped: list[tuple[str, str]] = field(default_factory=list)  # (line start, reason)


def tier_for(url: str) -> Tier:
    host = urlparse(url).hostname or ""
    if any(host == h or host.endswith("." + h) for h in KQM_HOSTS):
        return Tier.KQM
    # HoYoLAB *articles* are player posts; its wiki and map are official.
    if any(host == h or host.endswith("." + h) for h in OFFICIAL_HOSTS):
        return Tier.RAYY_VERIFIED
    return Tier.COMMUNITY


def newest_version(text: str) -> tuple[int, int] | None:
    found = [(int(a), int(b)) for a, b in _VERSION.findall(text)]
    return max(found) if found else None


def _problem(fact: str, url: str, version: str, live: tuple[int, int] | None) -> str | None:
    if urlparse(url).scheme != "https" or not urlparse(url).hostname:
        return "no https source"
    if LEAK_LANGUAGE.search(fact):
        return "leak language"
    if has_personal_data(fact):
        return "personal data"
    newest = newest_version(version)
    if live and newest and newest > live:
        return "newer than the live game"
    return None


def parse_facts(
    text: str, fetched_at: datetime, live: tuple[int, int] | None = None
) -> FactsResult:
    result = FactsResult()
    groups: dict[tuple[str, str], list[str]] = {}
    versions: dict[tuple[str, str], str] = {}
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if m := _SECTION.match(line):
            section = m.group(1)
            continue
        if not line.startswith("- "):
            continue
        m = _FACT.match(line)
        if not m or section is None:
            result.dropped.append((line[:60], "malformed"))
            continue
        fact, url, checked, version = m.groups()
        if reason := _problem(fact, url, version, live):
            result.dropped.append((line[:60], reason))
            continue
        key = (section, url)
        groups.setdefault(key, []).append(f"- {fact} (checked {checked}; applies to {version})")
        versions[key] = version
        result.kept_lines += 1

    seen: dict[str, int] = {}
    for (section, url), lines in groups.items():
        host = (urlparse(url).hostname or "").removeprefix("www.")
        slug = slugify(section)
        seen[slug] = seen.get(slug, 0) + 1
        newest = newest_version(versions[(section, url)])
        result.docs.append(
            Doc(
                doc_id=f"team/{slug}#{seen[slug]}",
                entity_id=None,
                kind="team_facts",
                title=f"{section} (team-checked, {host})",
                text=f"# {section}: team-checked facts\nSource: {url}\n" + "\n".join(lines),
                release=Release(status=ReleaseStatus.RELEASED),
                source=SourceRef(
                    source="team_facts",
                    url=url,
                    tier=tier_for(url),
                    fetched_at=fetched_at,
                    game_version=f"{newest[0]}.{newest[1]}" if newest else None,
                ),
            )
        )
    return result
