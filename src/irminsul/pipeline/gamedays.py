"""Should this run be a deep one? Decided from the game's own calendar.

Every run refreshes game data and official news. A deep run also re-reads the slow sources
(all quests, in-game books, build guides), so it runs:
- on the days the game changes: a version start, a wish phase change, the 1st and 16th
  (the monthly endgame resets), and the next version's expected start,
- and whenever the last deep run is more than a week old, so a skipped or failed run heals
  itself on the next one instead of waiting for a date.

The dates come from HoYoverse's wish notices (the `banners.json` of the last published build).
Without them the 1st, the 16th and the weekly rule still hold.

Usage:
    uv run irminsul-calendar --previous prev
"""

import argparse
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

WEEK = timedelta(days=7)
VERSION_LENGTH = timedelta(days=42)
RESET_DAYS = (1, 16)


def game_days(feed: dict) -> dict[str, str]:
    """ISO date -> why that day matters, from the official notices."""
    days: dict[str, str] = {}
    for banner in feed.get("banners", []):
        if banner.get("start"):
            days[banner["start"]] = f"wishes change (Version {banner['version']})"
    starts = sorted((day, v) for v, day in (feed.get("versions") or {}).items())
    for day, version in starts:
        days[day] = f"Version {version} starts"
    if starts:
        expected = date.fromisoformat(starts[-1][0]) + VERSION_LENGTH
        days.setdefault(expected.isoformat(), "the next version is expected")
    return days


def decide(feed: dict, now: datetime, deep_at: str | None, forced: bool = False) -> str | None:
    """Why this run should go deep, or None if it shouldn't."""
    if forced:
        return "asked for by hand"
    if not deep_at:
        return "no deep run on record"
    last = datetime.fromisoformat(deep_at)
    if now - last >= WEEK:
        return "weekly refresh"
    today = now.date()
    if last.date() == today:
        return None  # the day's deep run is done
    if reason := game_days(feed).get(today.isoformat()):
        return reason
    return "monthly endgame reset" if today.day in RESET_DAYS else None


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--previous", type=Path, default=Path("prev"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    deep_at = _json(args.previous / "manifest.json").get("deep_at")
    feed = _json(args.previous / "banners.json")
    reason = decide(feed, datetime.now(UTC), deep_at, args.force)
    print(f"Deep run: {reason}" if reason else "Quick run: nothing on the calendar today.")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"deep={'true' if reason else 'false'}\n")


if __name__ == "__main__":
    main()
