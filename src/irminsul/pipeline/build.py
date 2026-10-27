"""Build the corpus: fetch sources -> leak gate -> render docs -> write a versioned snapshot.

Usage:
    uv run irminsul-build --out data/build --cache data/cache
    uv run irminsul-build --limit 5     # quick dev run on a few items per type
    uv run irminsul-build --sources kqm # only some sources (default: all)
    uv run irminsul-build --sources yatta,hoyowiki,kqm,lore,books   # add in-game books too
"""

import argparse
import itertools
import json
import logging
from dataclasses import dataclass
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
    story_docs,
    weapon_docs,
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
    slugify,
)
from irminsul.sources import hoyowiki
from irminsul.sources.http import PoliteClient
from irminsul.sources.kqm import KqmSource
from irminsul.sources.notices import NoticesSource, fetch_notices
from irminsul.sources.team_facts import parse_facts
from irminsul.sources.yatta import SITE, YattaSource
from irminsul.story import Changelog, MentionDater, character_revealed_in, later

log = logging.getLogger("irminsul.build")

SOURCES = ("yatta", "hoyowiki", "kqm", "lore", "team_facts", "notices")
TEAM_FACTS = Path("config/team_facts.md")  # public team facts, approved by Ray (Oct 2026)
# In-game books: ~600 books and ~2,000 volume texts, one request each, so opt-in for now.
OPTIONAL_SOURCES = ("books",)


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


def fetch_official(
    wiki: hoyowiki.HoYoWikiSource, live: list[Character], now: datetime, limit: int | None
) -> Official:
    """Official name lists, announced characters and official videos from HoYoWiki.

    Announced = on HoYoWiki but not in the live game data. That comparison needs the full
    live roster, so partial (--limit) builds skip it and only sample videos.
    """
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
            if hoyowiki.page_has_kit(page):
                log.info("%s: official kit modules present (not ingested yet)", entry.name)
            official.announced.append(character)
            live_ids[key] = character.id
        entity_id = live_ids.get(key, f"character/{slugify(entry.name)}")
        official.videos += hoyowiki.parse_videos(page, entity_id, now)
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
            when[record.id] = changelog.version_of(category, record.game_id)
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
        if c.release.status != ReleaseStatus.RELEASED:
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


def build(
    out: Path,
    cache: Path | None,
    limit: int | None,
    blocklist: set[str],
    sources: tuple[str, ...] = SOURCES,
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

    # HoYoWiki confirms Yatta's records, so it only runs alongside Yatta.
    if "hoyowiki" in sources and fetched:
        wiki_client = PoliteClient(cache_dir=cache, headers=hoyowiki.HEADERS)
        try:
            official = fetch_official(
                hoyowiki.HoYoWikiSource(wiki_client), fetched["characters"], now, limit
            )
        finally:
            wiki_client.close()
        fetched["characters"] += official.announced
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
        counts["announced"] = [c.name for c in official.announced]
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
        source_info["kqm"] = {"game_version": sha, "license": "CC BY-NC-SA 4.0"}

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

    if "team_facts" in sources and TEAM_FACTS.exists():
        facts = parse_facts(
            TEAM_FACTS.read_text(encoding="utf-8"),
            now,
            version_from_manifest(source_info.get("yatta", {}).get("game_version")),
        )
        docs += facts.docs
        dropped += [(f"team_facts:{line}", reason) for line, reason in facts.dropped]
        counts["team_facts"] = {"lines": facts.kept_lines, "docs": len(facts.docs)}

    if "notices" in sources:
        # Never from the dev HTTP cache: news is only useful fresh
        news_client = PoliteClient(cache_dir=None)
        try:
            notices = fetch_notices(NoticesSource(news_client), now, live)
        finally:
            news_client.close()
        docs += notices
        counts["notices"] = len(notices)

    # Newer reactions are defined across many kits: compile each into one guide (no model).
    guides = reaction_guides(docs, now)
    docs += guides
    counts["reaction_guides"] = len(guides)

    if changelog is not None:
        stamp_revealed(docs, kept, changelog)
    check_unique_ids(docs)
    _write_jsonl(out / "docs.jsonl", docs)
    _write_jsonl(out / "videos.jsonl", official.videos)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "built_at": now.isoformat(),
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
    manifest = build(args.out, args.cache, args.limit, blocklist, args.sources)
    log.info(
        "counts=%s docs=%d dropped=%d unverified=%d",
        manifest["counts"],
        manifest["docs"],
        len(manifest["dropped"]),
        len(manifest["unverified"]),
    )


if __name__ == "__main__":
    main()
