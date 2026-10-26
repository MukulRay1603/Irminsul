"""Official Genshin Impact version release dates, and mapping release timestamps to versions.

Each date is the day a version update went live, as announced in HoYoverse's official update
notices (https://genshin.hoyoverse.com/en/news, also posted on HoYoLAB). Version 6.8 does not
exist: HoYoverse went from 6.7 straight to 7.0, which launched Snezhnaya on 12 August 2026.

Cross-check: Yatta's official release timestamps for characters (`Release.released_at`) fall on
or one to two days before these dates (they mark the start of the maintenance window in UTC), so
a timestamp up to GRACE before a version's date belongs to that version.

Only versions that are already out are listed. Add a row on patch day; until then, a new version
seen in the build history (`history.json`) is picked up from there.
"""

from datetime import UTC, date, datetime, timedelta

SOURCE_URL = "https://genshin.hoyoverse.com/en/news"
GRACE = timedelta(days=3)

VERSIONS: tuple[tuple[str, date], ...] = (
    ("1.0", date(2020, 9, 28)),
    ("1.1", date(2020, 11, 11)),
    ("1.2", date(2020, 12, 23)),
    ("1.3", date(2021, 2, 3)),
    ("1.4", date(2021, 3, 17)),
    ("1.5", date(2021, 4, 28)),
    ("1.6", date(2021, 6, 9)),
    ("2.0", date(2021, 7, 21)),
    ("2.1", date(2021, 9, 1)),
    ("2.2", date(2021, 10, 13)),
    ("2.3", date(2021, 11, 24)),
    ("2.4", date(2022, 1, 5)),
    ("2.5", date(2022, 2, 16)),
    ("2.6", date(2022, 3, 30)),
    ("2.7", date(2022, 5, 31)),
    ("2.8", date(2022, 7, 13)),
    ("3.0", date(2022, 8, 24)),
    ("3.1", date(2022, 9, 28)),
    ("3.2", date(2022, 11, 2)),
    ("3.3", date(2022, 12, 7)),
    ("3.4", date(2023, 1, 18)),
    ("3.5", date(2023, 3, 1)),
    ("3.6", date(2023, 4, 12)),
    ("3.7", date(2023, 5, 24)),
    ("3.8", date(2023, 7, 5)),
    ("4.0", date(2023, 8, 16)),
    ("4.1", date(2023, 9, 27)),
    ("4.2", date(2023, 11, 8)),
    ("4.3", date(2023, 12, 20)),
    ("4.4", date(2024, 1, 31)),
    ("4.5", date(2024, 3, 13)),
    ("4.6", date(2024, 4, 24)),
    ("4.7", date(2024, 6, 5)),
    ("4.8", date(2024, 7, 17)),
    ("5.0", date(2024, 8, 28)),
    ("5.1", date(2024, 10, 9)),
    ("5.2", date(2024, 11, 20)),
    ("5.3", date(2025, 1, 1)),
    ("5.4", date(2025, 2, 12)),
    ("5.5", date(2025, 3, 26)),
    ("5.6", date(2025, 5, 7)),
    ("5.7", date(2025, 6, 18)),
    ("5.8", date(2025, 7, 30)),
    ("6.0", date(2025, 9, 10)),
    ("6.1", date(2025, 10, 22)),
    ("6.2", date(2025, 12, 3)),
    ("6.3", date(2026, 1, 14)),
    ("6.4", date(2026, 2, 25)),
    ("6.5", date(2026, 4, 8)),
    ("6.6", date(2026, 5, 20)),
    ("6.7", date(2026, 7, 1)),
    ("7.0", date(2026, 8, 12)),
    ("7.1", date(2026, 9, 23)),
)


def key(version: str) -> tuple[int, int]:
    major, _, minor = version.partition(".")
    return int(major), int(minor or 0)


def from_data_version(game_version: str | None) -> str | None:
    """Yatta reports e.g. '71F2' for 7.1."""
    if game_version and len(game_version) >= 2 and game_version[:2].isdigit():
        return f"{game_version[0]}.{game_version[1]}"
    return None


def released_versions(now: datetime, extra: dict[str, date] | None = None) -> dict[str, date]:
    """Version -> release date for every version already out, oldest first.

    `extra` adds versions the table doesn't list yet (first seen in the build history); a table
    date always wins. Nothing dated after `now` is returned.
    """
    today = now.astimezone(UTC).date()
    starts = {**(extra or {}), **dict(VERSIONS)}
    return {v: d for v, d in sorted(starts.items(), key=lambda x: key(x[0])) if d <= today}


def version_of(when: datetime, starts: dict[str, date]) -> str | None:
    """The version a release timestamp belongs to, or None if it predates every version."""
    day = (when.astimezone(UTC) + GRACE).date()
    found = None
    for version, start in sorted(starts.items(), key=lambda x: x[1]):
        if start <= day:
            found = version
    return found
