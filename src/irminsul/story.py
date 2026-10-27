"""Story-safe mode: which game version a player's Archon Quest progress covers.

Story content ships version by version, so every lore doc carries `revealed_in`, the game
version that first made it public. A player who says "I've finished the Archon Quest up to
Inazuma" gets a version ceiling, and retrieval hides everything revealed after it.

`revealed_in` is a ceiling we can prove from official live data, never a guess:
- Yatta's per-version changelog (gi.yatta.moe/api/v2/static/changelog) lists the items each
  version added, from 3.0 on for characters and weapons and from 3.2 on for books;
- characters older than that carry an official release time, mapped to a version below;
- anything else older than the changelog gets the last version before tracking began, so
  it can only ever be hidden too early, never shown too early;
- text with no date of its own (guides, boss pages, old weapons) takes the latest version
  of any character it names.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

Version = tuple[int, int]

# Version start dates before Yatta's changelog begins (HoYoverse's official version notes).
# Each version's own date marks the first day of its maintenance window (UTC+8 morning).
PRE_CHANGELOG = {
    "1.0": "2020-09-28",
    "1.1": "2020-11-11",
    "1.2": "2020-12-23",
    "1.3": "2021-02-03",
    "1.4": "2021-03-17",
    "1.5": "2021-04-28",
    "1.6": "2021-06-09",
    "2.0": "2021-07-21",
    "2.1": "2021-09-01",
    "2.2": "2021-10-13",
    "2.3": "2021-11-24",
    "2.4": "2022-01-05",
    "2.5": "2022-02-16",
    "2.6": "2022-03-30",
    "2.7": "2022-05-31",
    "2.8": "2022-07-13",
}
# Yatta's release times can fall a little before the launch day (Raiden Shogun: the evening
# before 2.1 in UTC; Albedo: two days before 1.2). Banners never open in a version's last
# days, so a few days of slack cannot push anyone into the wrong version.
RELEASE_SLACK = timedelta(days=3)


def parse_version(text: str | None) -> Version | None:
    """Parse "7.1" to (7, 1). Anything else (None, "71F2", "") gives None."""
    major, sep, minor = (text or "").strip().partition(".")
    if not (sep and major.isdigit() and minor.isdigit()):
        return None
    return int(major), int(minor)


def later(a: str | None, b: str | None) -> bool:
    """Is version `a` after version `b`? Unknown versions are never 'later'."""
    va, vb = parse_version(a), parse_version(b)
    return va is not None and vb is not None and va > vb


@dataclass(frozen=True)
class StoryPoint:
    key: str  # what the browser sends as `story_until`
    label: str  # region, as players name their progress
    chapter: str  # the Archon Quest chapter that finishes it
    until: str  # the last game version this point covers


# "I've finished the Archon Quest up to <region>" -> everything released before the next
# region's chapter opened. Chapter versions are from Yatta's live quest list
# (gi.yatta.moe/api/v2/en/quest, type "aq") joined with its changelog (quests tracked from
# 3.6), and from HoYoverse's version notes before that:
# - Prologue (Mondstadt) shipped in 1.0. Chapter I (Liyue) also opened in 1.0, so finishing
#   Mondstadt covers 1.0: its characters were all on the launch banners anyway.
# - Chapter II (Inazuma) opened in 2.0, so finishing Liyue covers 1.0-1.6.
# - Chapter III (Sumeru) opened in 3.0; Chapter IV (Fontaine) in 4.0 (Acts I-II);
#   Chapter V (Natlan) in 5.0 (Acts I-II), ending with Act VI in 5.7.
# - Song of the Welkin Moon (Nod-Krai) opened with its Prelude in 5.8, so Natlan covers 5.7.
# - Chapter VII (Snezhnaya) opened in 7.0 (Acts I-II), so Nod-Krai covers 6.0-6.7.
# Snezhnaya is the chapter still being written: finishing it means "everything released",
# which is the picker's no-filter default. When Chapter VIII opens, add Snezhnaya here.
STORY_POINTS: tuple[StoryPoint, ...] = (
    StoryPoint("mondstadt", "Mondstadt", "Prologue", "1.0"),
    StoryPoint("liyue", "Liyue", "Chapter I", "1.6"),
    StoryPoint("inazuma", "Inazuma", "Chapter II", "2.8"),
    StoryPoint("sumeru", "Sumeru", "Chapter III", "3.8"),
    StoryPoint("fontaine", "Fontaine", "Chapter IV", "4.8"),
    StoryPoint("natlan", "Natlan", "Chapter V", "5.7"),
    StoryPoint("nod-krai", "Nod-Krai", "Song of the Welkin Moon", "6.7"),
    StoryPoint("snezhnaya", "Snezhnaya", "Chapter VII: Act I", "7.0"),
)
BY_KEY = {p.key: p for p in STORY_POINTS}


def point(key: str | None) -> StoryPoint | None:
    """The story point for a `story_until` key; None means no filter. Unknown keys raise."""
    if not key:
        return None
    if key not in BY_KEY:
        raise ValueError(f"unknown story point {key!r}")
    return BY_KEY[key]


def hides(p: StoryPoint | None, revealed_in: str | None) -> bool:
    """Does story point `p` hide content revealed in `revealed_in`? Undated content shows."""
    return p is not None and later(revealed_in, p.until)


def filter_info(p: StoryPoint, hidden: int) -> dict:
    """The trace entry the UI shows as "Spoiler filter: up to <region>, N passages hidden"."""
    return {"until": p.key, "label": p.label, "max_version": p.until, "hidden": hidden}


# ---- revealed_in from official data ----------------------------------------------------
class Changelog:
    """Yatta's per-version changelog: which version first added each item, per category."""

    def __init__(self, data: dict) -> None:
        self.added: dict[str, dict[str, str]] = {}  # category -> item id -> version
        self.versions: set[str] = set(PRE_CHANGELOG)
        self.first_tracked: dict[str, str] = {}  # category -> first version that lists it
        entries = sorted(
            (v for v in data.values() if parse_version(v.get("version"))),
            key=lambda v: parse_version(v["version"]),
        )
        for entry in entries:
            version = entry["version"]
            self.versions.add(version)
            for category, ids in (entry.get("items") or {}).items():
                self.first_tracked.setdefault(category, version)
                added = self.added.setdefault(category, {})
                for item_id in ids:
                    added.setdefault(str(item_id), version)

    def latest(self) -> str | None:
        return max(self.versions, key=parse_version, default=None)

    def before(self, version: str) -> str | None:
        """The last known version before `version`."""
        v = parse_version(version)
        older = [x for x in self.versions if parse_version(x) < v]
        return max(older, key=parse_version, default=None)

    def untracked_ceiling(self, category: str) -> str | None:
        """Ceiling for an item the changelog doesn't list: it predates tracking."""
        first = self.first_tracked.get(category)
        return self.before(first) if first else None

    def version_of(self, category: str, *item_ids: str) -> str | None:
        added = self.added.get(category, {})
        return next((added[str(i)] for i in item_ids if str(i) in added), None)


def version_at(when: datetime) -> str | None:
    """The pre-changelog version live at `when`, or None if it is after the last one."""
    first_after = datetime.fromisoformat("2022-08-24").replace(tzinfo=UTC)  # 3.0
    if when >= first_after:
        return None
    current = None
    for version, start in PRE_CHANGELOG.items():
        if when + RELEASE_SLACK >= datetime.fromisoformat(start).replace(tzinfo=UTC):
            current = version
    return current


class MentionDater:
    """Dates undated text by the characters it names: a page about the Shogun boss fight
    can't be read before the Raiden Shogun is out. It only ever makes text hide earlier."""

    def __init__(self, names: dict[str, str]) -> None:
        self.names = names  # name as written in text -> the version that character came out
        alternatives = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        self.pattern = re.compile(rf"\b(?:{alternatives})\b") if names else None

    def __call__(self, text: str) -> str | None:
        if self.pattern is None:
            return None
        found = {self.names[m] for m in self.pattern.findall(text)}
        return max(found, key=parse_version, default=None)


def character_revealed_in(
    game_id: str, released_at: datetime | None, changelog: Changelog, live: str | None
) -> str | None:
    """The version a released character (and so their stories) became public.

    The changelog re-lists some older characters when their data changes (Venti shows up
    again in 6.2), so a release time from before the changelog wins over a later listing.
    A listing in the changelog's very first version is ambiguous (the Dendro Traveler's
    release time says 2.8, the changelog 3.0), so the later of the two wins: hiding a little
    too early is fine, showing too early is a spoiler. Anything unproven counts as the live
    version, which hides it under every story point.
    """
    listed = changelog.version_of("avatar", game_id)
    dated = version_at(released_at) if released_at is not None else None
    if dated is None:
        return listed or live or changelog.latest()
    if listed is not None and listed == changelog.first_tracked.get("avatar"):
        return listed
    return dated
