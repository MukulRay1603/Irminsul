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

Topics: a fact can end with tags such as `#fates`, and `config/fact_topics.toml` tags lines by
section and wording, so an exact answer (the Fates answer, engine.py) finds its lines wherever
they sit in the file. Tags travel in the line's note: "(checked ...; applies to ...; topics:
fates)".

Re-checks (pipeline/recheck.py): a line behind the live version that its source page still
confirms is stamped for the live version; one the page no longer confirms is dropped.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

from irminsul.engine.guards import has_personal_data
from irminsul.pipeline.recheck import CHANGED, OK, Line
from irminsul.pipeline.safety import LEAK_LANGUAGE
from irminsul.schema import Doc, Release, ReleaseStatus, SourceRef, Tier, slugify

_SECTION = re.compile(r"^##\s+(?:\d+\.\s*)?(.+?)\s*$")
_FACT = re.compile(r"^-\s+(.+?)\s+\|\s+(\S+)\s+\|\s+(\d{4}-\d{2}-\d{2})\s+\|\s+(.+?)\s*$")
_VERSION = re.compile(r"\b(\d+)\.(\d+)\b")
_TAGS = re.compile(r"(?:\s+#[a-z][a-z0-9-]*)+\s*$")  # "... 160 Primogems. #fates"

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


def _version_key(text: str) -> tuple[int, int]:
    return newest_version(text) or (0, 0)


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


def split_tags(fact: str) -> tuple[str, list[str]]:
    """ "... 160 Primogems. #fates" -> ("... 160 Primogems.", ["fates"])."""
    if t := _TAGS.search(fact):
        return fact[: t.start()].rstrip(), [w.lstrip("#") for w in t.group(0).split()]
    return fact, []


def fact_lines(text: str) -> list[Line]:
    """Every well-formed fact line of a curated file, as the re-check reads it."""
    out = []
    for raw in text.splitlines():
        if m := _FACT.match(raw.strip()):
            fact, url, checked, version = m.groups()
            out.append(Line(split_tags(fact)[0], url, checked, version))
    return out


def parse_facts(
    text: str,
    fetched_at: datetime,
    live: tuple[int, int] | None = None,
    prefix: str = "team",
    what: str = "facts",
    checked_by: str = "team-checked",
    checks: dict | None = None,
    topics: list[dict] | None = None,
) -> FactsResult:
    """`prefix` keeps doc ids apart between files; `what` names their content ("builds").
    `checks` is the last `fact_checks.json`; `topics` the rules from fact_topics.toml."""
    verdicts = (checks or {}).get("facts", {})
    checked_for = (checks or {}).get("live")
    result = FactsResult()
    label = "" if what == "facts" else f" {what}"
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
        fact, tags = split_tags(fact)
        if reason := _problem(fact, url, version, live):
            result.dropped.append((line[:60], reason))
            continue
        verdict = verdicts.get(Line(fact, url, checked, version).key, {})
        if verdict.get("on", "") >= checked and verdict.get("version") == checked_for:
            if verdict.get("status") == CHANGED:
                result.dropped.append((line[:60], "its source page no longer says this"))
                continue
            if verdict.get("status") == OK and checked_for:
                checked, version = f"{verdict['on']} by machine", checked_for
        for rule in topics or ():
            if rule.get("section", section) == section and re.search(rule["match"], fact):
                tags.append(rule["topic"])
        note = f"checked {checked}; applies to {version}"
        if tags:
            note += "; topics: " + ", ".join(dict.fromkeys(tags))
        key = (section, url)
        groups.setdefault(key, []).append(f"- {fact} ({note})")
        versions[key] = max(versions.get(key, version), version, key=_version_key)
        result.kept_lines += 1

    seen: dict[str, int] = {}
    for (section, url), lines in groups.items():
        host = (urlparse(url).hostname or "").removeprefix("www.")
        slug = slugify(section)
        seen[slug] = seen.get(slug, 0) + 1
        newest = newest_version(versions[(section, url)])
        result.docs.append(
            Doc(
                doc_id=f"{prefix}/{slug}#{seen[slug]}",
                entity_id=None,
                kind=f"team_{what}",
                title=f"{section}{label} ({checked_by}, {host})",
                text=f"# {section}: {checked_by} {what}\nSource: {url}\n" + "\n".join(lines),
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
