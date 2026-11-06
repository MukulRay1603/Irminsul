"""Is the build as new as the game? Run after every publish; a failure opens an issue.

The safety gates ask "is anything unsafe?". This asks "is anything out of date?", using
HoYoverse's own notices as the truth:
- everyone on a wish that has started must be a released character in our data,
- the newest version with an update notice must be the version our game data says is live,
- there must be a wish open or announced.

Usage:
    uv run irminsul-freshness --build data/build
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from irminsul.engine.guards import version_from_manifest
from irminsul.pipeline.gate import normalise_name
from irminsul.sources.banners import active, proven_live, upcoming


def check(build: Path, now: datetime) -> list[str]:
    problems = []
    feed_path = build / "banners.json"
    feed = json.loads(feed_path.read_text(encoding="utf-8")) if feed_path.exists() else {}
    if not feed.get("banners"):
        return ["no wish banners parsed from the official notices"]

    released = set()
    for line in (build / "characters.jsonl").read_text(encoding="utf-8").splitlines():
        c = json.loads(line) if line else None
        if c and c["release"]["status"] == "released":
            released.add(normalise_name(c["name"]))
    for name in proven_live(feed, now):
        key = normalise_name(name)
        if not any(r == key or r.endswith(key) for r in released):
            problems.append(f"{name} is on an official wish but isn't a released character here")

    manifest = json.loads((build / "manifest.json").read_text(encoding="utf-8"))
    live = version_from_manifest(manifest.get("sources", {}).get("yatta", {}).get("game_version"))
    today = now.date().isoformat()
    started = [v for v, day in feed.get("versions", {}).items() if day <= today]
    newest = max(started, default=None)
    if live and newest and tuple(int(x) for x in newest.split(".")) > live:
        problems.append(f"the game is on {newest} but our game data says {live[0]}.{live[1]}")

    if not active(feed, now.date()) and not upcoming(feed, now.date()):
        problems.append("no wish is open or announced: the banner notices may have changed format")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--build", type=Path, default=Path("data/build"))
    args = parser.parse_args()
    problems = check(args.build, datetime.now(UTC))
    for p in problems:
        print(f"STALE: {p}")
    if problems:
        sys.exit(1)
    print("Fresh: the build matches the official notices.")


if __name__ == "__main__":
    main()
