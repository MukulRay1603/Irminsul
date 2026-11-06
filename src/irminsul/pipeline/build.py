"""Build the corpus: fetch sources -> leak gate -> render docs -> write a versioned snapshot.

Usage:
    uv run irminsul-build --out data/build --cache data/cache
    uv run irminsul-build --limit 5     # quick dev run on a few items per type
    uv run irminsul-build --sources kqm # only some sources (default: all)
    uv run irminsul-build --deep --previous prev   # also quests, books and guides
"""

import argparse
import itertools
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from irminsul.engine.entities import ALIASES
from irminsul.engine.guards import version_from_manifest
from irminsul.pipeline.gate import gate, gate_linked_docs, normalise_name
from irminsul.pipeline.guides import reaction_guides
from irminsul.pipeline.planner import build_planner, parse_schedule
from irminsul.pipeline.render import (
    artifact_docs,
    book_docs,
    character_docs,
    quest_doc,
    story_docs,
    weapon_docs,
    wiki_quest_doc,
)
from irminsul.schema import (
    SCHEMA_VERSION,
    Character,
    Doc,
    Release,
    ReleaseStatus,
    SourceRef,
    Tier,
    Video,
    Weapon,
    slugify,
)
from irminsul.sources import hoyowiki
from irminsul.sources.banners import parse_banners, proven_live, proven_weapons
from irminsul.sources.guides import fetch_guide, guide_urls
from irminsul.sources.http import PoliteClient
from irminsul.sources.kqm import KqmSource
from irminsul.sources.notices import NoticesSource, fetch_notices
from irminsul.sources.team_facts import parse_facts
from irminsul.sources.yatta import QUEST_TYPES, SITE, YattaSource
from irminsul.story import (
    Changelog,
    MentionDater,
    character_revealed_in,
    later,
    parse_version,
)

log = logging.getLogger("irminsul.build")

SOURCES = ("yatta", "hoyowiki", "kqm", "lore", "team_facts", "notices")
TEAM_FACTS = Path("config/team_facts.md")  # public team facts, approved by Ray (Oct 2026)
# Build recommendations (weapons, sets, stats, teams), each line attributed to its guide
TEAM_BUILDS = Path("config/team_builds.md")
# The slow sources, thousands of requests between them: read on deep runs only (see
# gamedays.py). Every other run carries their docs forward from the last published build, and
# so does a deep run whose source fails: last good data stays until a better read replaces it.
OPTIONAL_SOURCES = ("books", "quests", "guides")
CARRIED = {"books": "book/", "quests": "quest/", "guides": "auto-builds/"}
_LUNA = re.compile(r"Luna ([IVX]+)")
_ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX")
_KQM_GUIDE = re.compile(r"https://keqingmains\.com/q/[\w-]+-quickguide/?")


def _write_jsonl(path: Path, rows: list[BaseModel]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(row.model_dump_json() + "\n")


def art_names_if_released(record: BaseModel) -> BaseModel:
    """Official image names stay on released records only: nothing announced ever gets art."""
    if record.release.status == ReleaseStatus.RELEASED:
        return record
    update: dict = {"icon": None}
    if isinstance(record, Character):
        update["namecard"] = None
        update["talents"] = [t.model_copy(update={"icon": None}) for t in record.talents]
        update["constellations"] = [
            c.model_copy(update={"icon": None}) for c in record.constellations
        ]
    return record.model_copy(update=update)


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
    weapons: list[Weapon] = field(default_factory=list)


def fetch_official(
    wiki: hoyowiki.HoYoWikiSource,
    live: list[Character],
    now: datetime,
    limit: int | None,
    proven: dict[str, str] | None = None,
    proven_gear: dict[str, str] | None = None,
    live_weapons: list[Weapon] | None = None,
) -> Official:
    """Official name lists, announced characters and official videos from HoYoWiki.

    Announced = on HoYoWiki but not in the live game data. That comparison needs the full
    live roster, so partial (--limit) builds skip it and only sample videos. `proven` names
    characters on an official wish that has started: they are playable, so they are built
    from their official page instead of waiting for the game-data mirrors to catch up.
    `proven_gear` does the same for weapons on a wish that has started.
    """
    proven = {normalise_name(k): v for k, v in (proven or {}).items()}
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
            if key in proven:
                opened = datetime.fromisoformat(proven[key]).replace(tzinfo=UTC)
                released = hoyowiki.released_character(entry, page, now, opened)
                if released is not None:
                    log.info("%s: on an official wish, built from the official page", entry.name)
                    character = released
            official.announced.append(character)
            live_ids[key] = character.id
        entity_id = live_ids.get(key, f"character/{slugify(entry.name)}")
        official.videos += hoyowiki.parse_videos(page, entity_id, now)
    known = {normalise_name(w.name) for w in live_weapons or []}
    proven_gear = {normalise_name(k): v for k, v in (proven_gear or {}).items()}
    for entry in entries["weapons"]:
        key = normalise_name(entry.name)
        if limit is None and key in proven_gear and key not in known:
            opened = datetime.fromisoformat(proven_gear[key]).replace(tzinfo=UTC)
            weapon = hoyowiki.released_weapon(entry, wiki.page(entry.entry_id), now, opened)
            if weapon is not None:
                log.info("%s: on an official wish, built from the official page", entry.name)
                official.weapons.append(weapon)
    return official


def live_version(yatta_version: str | None) -> str | None:
    """Yatta's '71F2' -> '7.1'."""
    v = version_from_manifest(yatta_version)
    return f"{v[0]}.{v[1]}" if v else None


def stamp_revealed(docs: list[Doc], kept: dict[str, list], changelog: Changelog) -> None:
    """Give every doc the version it became public, for story-safe mode.

    Entity docs (official or guide) take their entity's version. Docs still undated after
    that (boss pages, mechanics, pre-3.0 weapons) take the latest version of any character
    they name, so a page about the Shogun boss fight hides until the Raiden Shogun is out.
    """
    characters = kept.get("characters", [])
    when: dict[str, str | None] = {c.id: c.revealed_in for c in characters}
    for kind, category in (("weapons", "weapon"), ("artifact_sets", "reliquary")):
        for record in kept.get(kind, []):
            when[record.id] = changelog.version_of(category, record.game_id) or (
                changelog.latest() if record.game_id.startswith("hoyowiki:") else None
            )
    names = {c.name: c.revealed_in for c in characters if c.revealed_in and "(" not in c.name}
    names |= {
        alias.title(): when[eid]
        for alias, eid in ALIASES.items()
        if eid.startswith("character/") and when.get(eid)
    }
    dater = MentionDater(names)
    for doc in docs:
        if doc.revealed_in is None and doc.entity_id in when:
            doc.revealed_in = when[doc.entity_id]
        if doc.revealed_in is None:
            doc.revealed_in = dater(doc.text)


def fetch_lore(
    yatta: YattaSource,
    characters: list[Character],
    changelog: Changelog,
    live: str | None,
    now: datetime,
    blocklist: set[str],
    books: bool,
    limit: int | None,
) -> tuple[list[Doc], list[tuple[str, str]], dict]:
    """Official lore for story-safe mode: character stories (and, opt-in, in-game books).

    Leak safety: stories are fetched only for characters the gate kept as *released*, never
    for announced ones, and any text revealed after the live version is dropped.
    """
    docs, dropped = [], []
    # The Traveler has one entry per element ("10000005-anemo") but one profile, served under
    # the base id: it goes to the earliest-revealed element only.
    by_profile: dict[str, Character] = {}
    for c in characters:
        # Built from an official page: Yatta has no stories for them yet
        if c.release.status != ReleaseStatus.RELEASED or c.game_id.startswith("hoyowiki:"):
            continue
        profile = c.game_id.split("-")[0]
        current = by_profile.get(profile)
        if current is None or later(current.revealed_in, c.revealed_in):
            by_profile[profile] = c
    released = list(by_profile.items())
    for profile, c in released[:limit] if limit else released:
        try:
            docs += story_docs(c, yatta.character_stories(profile))
        except Exception:
            log.exception("no stories for %s", c.id)
    counts = {"stories": len(docs)}
    if books:
        fetched = 0
        for book, volumes in yatta.books():
            entity = f"book/{book['id']}"
            if entity in blocklist:
                dropped.append((entity, "blocklisted"))
                continue
            dated = [
                (
                    v,
                    text,
                    changelog.version_of("book", v["id"], book["id"])
                    or changelog.untracked_ceiling("book"),
                )
                for v, text in volumes
            ]
            source = SourceRef(
                source="yatta",
                url=f"{SITE}/archive/book/{book['id']}",
                tier=Tier.OFFICIAL,
                fetched_at=now,
                game_version=live,
            )
            docs += book_docs(book, dated, Release(status=ReleaseStatus.RELEASED), source)
            fetched += 1
            if limit and fetched >= limit:
                break
        counts["books"] = fetched
        counts["book_volumes"] = len(docs) - counts["stories"]
    kept = []
    for doc in docs:
        if later(doc.revealed_in, live):
            dropped.append((doc.doc_id, f"revealed in {doc.revealed_in}, after live {live}"))
        else:
            kept.append(doc)
    return kept, dropped, counts


def wiki_version(text: str) -> str | None:
    """HoYoWiki's "Version Released": "7.0", or "Luna VIII" for the versions the game numbers
    6.0 to 6.8. Anything else is None, and the caller treats it as the newest version."""
    if parse_version(text):
        return text
    if m := _LUNA.fullmatch(text.strip()):
        return f"6.{_ROMAN.index(m.group(1))}"
    return None


def fetch_quests(
    yatta: YattaSource,
    wiki: hoyowiki.HoYoWikiSource,
    changelog: Changelog,
    live: str | None,
    now: datetime,
    limit: int | None,
) -> tuple[list[Doc], list[tuple[str, str]]]:
    """Every Archon, Story and World Quest, plus the official wiki page where one exists.

    Quests carry the version that added them, as lore does, so story-safe mode can hide them.
    The changelog tracks quests from 3.6: an unlisted quest is older than that.
    """
    released = Release(status=ReleaseStatus.RELEASED)
    docs: list[Doc] = []
    added = changelog.added.get("quest", {})
    newest = [quest_id for quest_id, version in added.items() if version == live]
    for quest in itertools.islice(yatta.quests(newest), limit):
        info = quest["info"]
        when = changelog.version_of("quest", info["id"]) or changelog.untracked_ceiling("quest")
        source = SourceRef(
            source="yatta",
            url=f"{SITE}/archive/quest/{info['id']}",
            tier=Tier.OFFICIAL,
            fetched_at=now,
            game_version=live,
        )
        docs.append(quest_doc(quest, QUEST_TYPES[info["type"]], released, source, when))
    for entry in itertools.islice(wiki.entries(hoyowiki.MENU_QUESTS), limit):
        if page := hoyowiki.quest_page(wiki.page(entry.entry_id)):
            source = SourceRef(
                source="hoyowiki",
                url=hoyowiki.PAGE_URL.format(entry.entry_id),
                tier=Tier.OFFICIAL,
                fetched_at=now,
            )
            page["version"] = wiki_version(page["version"]) or live or ""
            docs.append(wiki_quest_doc(entry.entry_id, entry.name, page, released, source))
    kept = [d for d in docs if not later(d.revealed_in, live)]
    dropped = [
        (d.doc_id, f"revealed in {d.revealed_in}, after live {live}")
        for d in docs
        if later(d.revealed_in, live)
    ]
    return kept, dropped


def curated_guides(builds: str) -> dict[str, tuple[str, str]]:
    """Each section of the team's build file that cites a KQM quick guide:
    section -> (guide URL, date the team last checked it)."""
    found: dict[str, tuple[str, str]] = {}
    section = None
    for line in builds.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        elif section and (m := _KQM_GUIDE.search(line)):
            checked = re.search(r"\d{4}-\d{2}-\d{2}", line[m.end() :])
            found[section] = (m.group(), checked.group() if checked else "")
    return found


def read_guides(
    characters: list[Character],
    weapons: list[Weapon],
    sets: list,
    curated: str,
    live: str | None,
    now: datetime,
) -> tuple[str, dict]:
    """Fact lines for characters with no team build, and for guides updated since the team
    last read them. Returns the lines as a facts file, and what happened."""
    known_weapons = {normalise_name(w.name) for w in weapons}
    known_sets = {normalise_name(a.name) for a in sets}
    watched = curated_guides(curated)
    covered = {normalise_name(s) for s in re.findall(r"^## (.+)$", curated, re.M)}

    def has_team_build(c: Character) -> bool:  # the team writes "Kazuha", the game a full name
        return bool({normalise_name(c.name), *map(normalise_name, c.name.split())} & covered)

    today = now.date().isoformat()
    lines: list[str] = []
    read: list[str] = []
    no_guide: list[str] = []
    client = PoliteClient(delay_s=1.5)
    try:
        for name, (url, checked) in watched.items():
            guide = fetch_guide(client, [url], known_weapons, known_sets)
            newer = guide and guide.modified and guide.modified > checked
            if newer and (found := guide.lines(live or "", today)):
                lines += [f"## {name}", *found]
                read.append(name)
        for c in characters:
            if c.release.status != ReleaseStatus.RELEASED or has_team_build(c):
                continue
            if "(" in c.name or c.name == "Traveler":
                continue
            guide = fetch_guide(client, guide_urls(c.name), known_weapons, known_sets)
            found = guide.lines(live or "", today) if guide else []
            if found:
                lines += [f"## {c.name}", *found]
                read.append(c.name)
            else:
                no_guide.append(c.name)
    finally:
        client.close()
    return "\n".join(lines), {"read": read, "no_guide": no_guide}


def carried_docs(previous: Path | None, sources: tuple[str, ...], live: str | None) -> list[Doc]:
    """Docs of the slow sources this build didn't read, from the last published build."""
    path = previous / "docs.jsonl" if previous else None
    prefixes = tuple(p for s, p in CARRIED.items() if s not in sources)
    if path is None or not path.exists() or not prefixes:
        return []
    docs = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            doc = Doc.model_validate_json(line)
            if doc.doc_id.startswith(prefixes) and not later(doc.revealed_in, live):
                docs.append(doc)
    return docs


def build(
    out: Path,
    cache: Path | None,
    limit: int | None,
    blocklist: set[str],
    sources: tuple[str, ...] = SOURCES,
    previous: Path | None = None,
) -> dict:
    now = datetime.now(UTC)
    take = (lambda it: itertools.islice(it, limit)) if limit else (lambda it: it)
    fetched: dict[str, list] = {}
    source_info: dict[str, dict] = {}
    official = Official({}, [], [], [])
    yatta: YattaSource | None = None
    schedule: list[dict] = []
    changelog: Changelog | None = None
    live: str | None = None

    if "yatta" in sources:
        client = PoliteClient(cache_dir=cache)
        yatta = YattaSource(client)
        try:
            version = yatta.game_version()
            log.info("Yatta live data version: %s", version)
            changelog = Changelog(yatta.changelog())
            live = live_version(version)
            fetched = {
                "characters": list(take(yatta.characters(now, version))),
                "weapons": list(take(yatta.weapons(now, version))),
                "artifact_sets": list(take(yatta.artifact_sets(now, version))),
            }
            schedule = parse_schedule(yatta.daily_schedule())
            source_info["yatta"] = {"game_version": version}
        finally:
            client.close()

    # Official news first: its wish notices prove who is live for the steps below
    notices: list[Doc] = []
    if "notices" in sources:
        # Never from the dev HTTP cache: news is only useful fresh
        news_client = PoliteClient(cache_dir=None)
        try:
            notices = fetch_notices(NoticesSource(news_client), now, live)
        finally:
            news_client.close()
    feed = parse_banners(notices)

    # HoYoWiki confirms Yatta's records, so it only runs alongside Yatta.
    if "hoyowiki" in sources and fetched:
        wiki_client = PoliteClient(cache_dir=cache, headers=hoyowiki.HEADERS)
        try:
            official = fetch_official(
                hoyowiki.HoYoWikiSource(wiki_client),
                fetched["characters"],
                now,
                limit,
                proven_live(feed, now),
                proven_weapons(feed, now),
                fetched["weapons"],
            )
        finally:
            wiki_client.close()
        fetched["characters"] += official.announced
        fetched["weapons"] += official.weapons
        source_info["hoyowiki"] = {"official_names": {k: len(v) for k, v in official.names.items()}}
        log.info(
            "HoYoWiki: %s official names, %d announced, %d videos",
            source_info["hoyowiki"]["official_names"],
            len(official.announced),
            len(official.videos),
        )

    if changelog is not None:
        # Story-safe mode: the version each character became public. Announced characters
        # are not out yet, so they are past every story point.
        for c in fetched["characters"]:
            c.revealed_in = (
                live
                if c.release.status == ReleaseStatus.ANNOUNCED
                else character_revealed_in(c.game_id, c.release.released_at, changelog, live)
            )

    out.mkdir(parents=True, exist_ok=True)
    renderers = {
        "characters": character_docs,
        "weapons": weapon_docs,
        "artifact_sets": artifact_docs,
    }
    docs, dropped, unverified, counts = [], [], [], {}
    kept: dict[str, list] = {}
    for kind, records in fetched.items():
        # Only full builds with HoYoWiki may drop undated records it does not list.
        names = official.names.get(kind) if limit is None and official.names else None
        report = gate(records, now, blocklist, official_names=names)
        report.kept = [art_names_if_released(r) for r in report.kept]
        kept[kind] = report.kept
        _write_jsonl(out / f"{kind}.jsonl", report.kept)
        for record in report.kept:
            docs.extend(renderers[kind](record))
        dropped += report.dropped
        unverified += report.unverified
        counts[kind] = {"fetched": len(records), "kept": len(report.kept)}
    if official.names:
        counts["announced"] = [
            c.name for c in official.announced if c.release.status == ReleaseStatus.ANNOUNCED
        ]
        counts["videos"] = len(official.videos)

    if "kqm" in sources:
        kqm = KqmSource(cache_dir=cache)
        try:
            sha = kqm.fetch()
            log.info("KQM TCL commit: %s", sha)
            pages = list(take(kqm.pages(now, blocklist)))
        finally:
            kqm.close()
        # KQM pages carry no release data: only serve character pages for characters
        # that are *released* according to official data in this same build.
        released = (
            {c.id for c in kept.get("characters", []) if c.release.status == ReleaseStatus.RELEASED}
            if "yatta" in sources and not limit
            else None
        )
        kqm_docs, linked_drops, linked_unverified = gate_linked_docs(
            [d for _, page in pages for d in page.docs], released
        )
        docs += kqm_docs
        dropped += [drop for _, page in pages for drop in page.dropped] + linked_drops
        unverified += linked_unverified
        counts["kqm"] = {"pages": len(pages), "docs": len(kqm_docs)}
        source_info["kqm"] = {"game_version": sha, "license": "none stated, see DATA_SOURCES.md"}

    if yatta is not None:
        # Only records the gate kept reach the planner; it skips announced characters itself.
        planner = build_planner(
            kept.get("characters", []),
            yatta.character_materials,
            kept.get("weapons", []),
            yatta.weapon_materials,
            schedule,
            source_info["yatta"]["game_version"],
            now.isoformat(),
        )
        (out / "planner.json").write_text(
            json.dumps(planner, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        counts["planner"] = {
            "characters": len(planner["characters"]),
            "weapons": len(planner["weapons"]),
        }

    if changelog is not None and ("lore" in sources or "books" in sources):
        lore_client = PoliteClient(cache_dir=cache)
        try:
            lore_docs, lore_dropped, counts["lore"] = fetch_lore(
                YattaSource(lore_client),
                kept.get("characters", []),
                changelog,
                live,
                now,
                blocklist,
                books="books" in sources,
                limit=limit,
            )
        finally:
            lore_client.close()
        docs += lore_docs
        dropped += lore_dropped
        log.info("lore: %s", counts["lore"])

    # A deep source that fails keeps its last good docs: it's removed from `read` below
    read = set(sources)
    if "quests" in sources and changelog is not None:
        quest_client = PoliteClient(cache_dir=cache)
        wiki_client = PoliteClient(cache_dir=cache, headers=hoyowiki.HEADERS)
        try:
            quest_docs, quest_dropped = fetch_quests(
                YattaSource(quest_client),
                hoyowiki.HoYoWikiSource(wiki_client),
                changelog,
                live,
                now,
                limit,
            )
            docs += quest_docs
            dropped += quest_dropped
            counts["quests"] = len(quest_docs)
        except Exception:
            log.exception("quests failed: keeping the last good ones")
            read.discard("quests")
        finally:
            quest_client.close()
            wiki_client.close()
    elif "quests" in sources:
        read.discard("quests")

    if "guides" in sources:
        curated = TEAM_BUILDS.read_text(encoding="utf-8") if TEAM_BUILDS.exists() else ""
        try:
            guide_lines, counts["guides"] = read_guides(
                kept.get("characters", []),
                kept.get("weapons", []),
                kept.get("artifact_sets", []),
                curated,
                live,
                now,
            )
            auto = parse_facts(
                guide_lines,
                now,
                version_from_manifest(source_info.get("yatta", {}).get("game_version")),
                prefix="auto-builds",
                what="builds",
                checked_by="read from the guide by machine",
            )
            docs += auto.docs
            dropped += [(f"auto_builds:{line}", reason) for line, reason in auto.dropped]
        except Exception:
            log.exception("guides failed: keeping the last good ones")
            read.discard("guides")

    carried = carried_docs(previous, tuple(read), live)
    docs += carried
    counts["carried"] = len(carried)

    if "team_facts" in sources and TEAM_FACTS.exists():
        facts = parse_facts(
            TEAM_FACTS.read_text(encoding="utf-8"),
            now,
            version_from_manifest(source_info.get("yatta", {}).get("game_version")),
        )
        docs += facts.docs
        dropped += [(f"team_facts:{line}", reason) for line, reason in facts.dropped]
        counts["team_facts"] = {"lines": facts.kept_lines, "docs": len(facts.docs)}
    if "team_facts" in sources and TEAM_BUILDS.exists():
        builds = parse_facts(
            TEAM_BUILDS.read_text(encoding="utf-8"),
            now,
            version_from_manifest(source_info.get("yatta", {}).get("game_version")),
            prefix="team-builds",
            what="builds",
        )
        docs += builds.docs
        dropped += [(f"team_builds:{line}", reason) for line, reason in builds.dropped]
        counts["team_builds"] = {"lines": builds.kept_lines, "docs": len(builds.docs)}

    docs += notices
    counts["notices"] = len(notices)
    counts["banners"] = len(feed["banners"])

    # Newer reactions are defined across many kits: compile each into one guide (no model).
    guides = reaction_guides(docs, now)
    docs += guides
    counts["reaction_guides"] = len(guides)

    if changelog is not None:
        stamp_revealed(docs, kept, changelog)
    check_unique_ids(docs)
    _write_jsonl(out / "docs.jsonl", docs)
    _write_jsonl(out / "videos.jsonl", official.videos)
    (out / "banners.json").write_text(json.dumps(feed, ensure_ascii=False), encoding="utf-8")

    deep = all(s in sources for s in CARRIED)
    last = previous / "manifest.json" if previous else None
    last_deep = (
        json.loads(last.read_text("utf-8")).get("deep_at") if last and last.exists() else None
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "built_at": now.isoformat(),
        "deep_at": now.isoformat() if deep else last_deep,
        "sources": source_info,
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
    parser.add_argument(
        "--sources",
        type=lambda s: tuple(x.strip() for x in s.split(",") if x.strip()),
        default=SOURCES,
        help=f"comma-separated subset of {','.join(SOURCES + OPTIONAL_SOURCES)} "
        f"(default: {','.join(SOURCES)})",
    )
    parser.add_argument(
        "--deep", action="store_true", help="also read the slow sources (quests, books, guides)"
    )
    parser.add_argument(
        "--previous", type=Path, default=None, help="last published build: slow docs carry over"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    blocklist: set[str] = set()
    if args.blocklist.exists():
        blocklist = {
            line.strip()
            for line in args.blocklist.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        }
    if unknown := set(args.sources) - set(SOURCES + OPTIONAL_SOURCES):
        parser.error(f"unknown sources: {', '.join(sorted(unknown))}")
    sources = args.sources + OPTIONAL_SOURCES if args.deep else args.sources
    manifest = build(args.out, args.cache, args.limit, blocklist, sources, args.previous)
    log.info(
        "counts=%s docs=%d dropped=%d unverified=%d",
        manifest["counts"],
        manifest["docs"],
        len(manifest["dropped"]),
        len(manifest["unverified"]),
    )


if __name__ == "__main__":
    main()
