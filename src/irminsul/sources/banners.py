"""Official Event Wish notices as data: what is on, when, and who is proven live.

Reading these with code matters twice. Models misread "After the Version 7.2 update -
2026/11/24 17:59" (that date is the end), so "what's on now?" is answered from parsed dates.
And a character on a wish that has started is officially playable, whatever the game-data
mirrors say yet, so the build can promote them without waiting for an upstream update.
"""

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from irminsul.schema import Doc

VERSION_CADENCE_DAYS = 42
_NOTICE = re.compile(r"Version (\d\.\d) Event Wishes Notice\s*-\s*Phase (I{1,2})\b", re.I)
_UPDATE = re.compile(r"Version (\d\.\d) Update Details", re.I)
_UPDATE_START = re.compile(r"Update maintenance begins (\d{4})/(\d{2})/(\d{2})")
_SECTION = re.compile(r'(?m)^(?:Event Wish|Chronicled Wish) "([^"]+)"')
_AFTER = re.compile(r"After the Version (\d\.\d) update\s*[—–-]\s*(\d{4}/\d{2}/\d{2})")
_RANGE = re.compile(r"(\d{4}/\d{2}/\d{2}) \d{2}:\d{2}\s*[—–-]\s*(\d{4}/\d{2}/\d{2})")
_CHARACTER = re.compile(r'"[^"]+" ([^"(]+?) \((?:Pyro|Hydro|Anemo|Electro|Dendro|Cryo|Geo)\)')
_WEAPON = re.compile(r"([A-Z][^,()]*?) \((?:Sword|Claymore|Polearm|Catalyst|Bow)\)")
_WEAPON_LEAD = re.compile(r"^.*?(?:weapons?|and|well as the)\s+(?=[A-Z])")


@dataclass
class Banner:
    name: str
    kind: str  # character | weapon | chronicled
    version: str
    phase: int
    start: str  # ISO dates, server time
    end: str
    five_stars: list[str] = field(default_factory=list)
    four_stars: list[str] = field(default_factory=list)
    source: str = ""


def _iso(text: str) -> str:
    return text.replace("/", "-")


def _weapons(line: str) -> list[str]:
    names = []
    for found in _WEAPON.findall(line):
        name = _WEAPON_LEAD.sub("", found).strip()
        name = re.sub(r"^(?:and|as well as the 4-star weapons)\s+", "", name)
        names.append(name)
    return names


def _section(
    text: str, version: str, phase: int, starts: dict[str, str], url: str
) -> Banner | None:
    head = _SECTION.search(text)
    if not head:
        return None
    if m := _AFTER.search(text):
        start = starts.get(m.group(1), "")
        end = _iso(m.group(2))
    elif m := _RANGE.search(text):
        start, end = _iso(m.group(1)), _iso(m.group(2))
    else:
        return None
    kind = "weapon" if "5-star weapons" in text else "character"
    if text.startswith("Chronicled"):
        kind = "chronicled"
    banner = Banner(head.group(1), kind, version, phase, start, end, source=url)
    for line in text.splitlines():
        if not line.startswith("●") or "drop" not in line.lower():
            continue
        if "5-star" in line and "4-star" not in line:
            banner.five_stars += _CHARACTER.findall(line) if kind != "weapon" else _weapons(line)
        elif "4-star" in line:
            banner.four_stars += _CHARACTER.findall(line) if kind != "weapon" else _weapons(line)
    return banner


def version_starts(notices: list[Doc]) -> dict[str, str]:
    """Version -> official start date, from each version's Update Details notice."""
    starts = {}
    for doc in notices:
        title = _UPDATE.search(doc.title)
        begins = _UPDATE_START.search(doc.text)
        if title and begins:
            starts[title.group(1)] = "-".join(begins.groups())
    return starts


def _estimate_start(version: str, starts: dict[str, str]) -> str:
    """A version with no Update Details yet: the one before it, plus the usual 42 days."""
    earlier = [v for v in starts if v < version]
    if not earlier:
        return ""
    last = max(earlier)
    return (date.fromisoformat(starts[last]) + timedelta(days=VERSION_CADENCE_DAYS)).isoformat()


def parse_banners(notices: list[Doc]) -> dict:
    """{"versions": {version: start}, "banners": [...]} from official notices."""
    starts = version_starts(notices)
    banners: list[Banner] = []
    for doc in notices:
        title = _NOTICE.search(doc.title)
        if not title:
            continue
        version, phase = title.group(1), len(title.group(2))
        known = {**starts, version: starts.get(version) or _estimate_start(version, starts)}
        body = doc.text.split("\n", 2)[-1]
        marks = [m.start() for m in _SECTION.finditer(body)]
        for a, b in zip(marks, [*marks[1:], len(body)], strict=True):
            if banner := _section(body[a:b], version, phase, known, doc.source.url):
                banners.append(banner)
    banners.sort(key=lambda x: (x.start, x.name), reverse=True)
    return {"versions": starts, "banners": [asdict(b) for b in banners]}


def proven_live(feed: dict, now: datetime) -> dict[str, str]:
    """Character -> the date their wish opened, for every wish that has already started."""
    today = now.date().isoformat()
    live: dict[str, str] = {}
    for b in feed.get("banners", []):
        if b["kind"] == "weapon" or not b["start"] or b["start"] > today:
            continue
        for name in b["five_stars"] + b["four_stars"]:
            if name not in live or b["start"] < live[name]:
                live[name] = b["start"]
    return live


def active(feed: dict, today: date) -> list[dict]:
    day = today.isoformat()
    return [b for b in feed.get("banners", []) if b["start"] and b["start"] <= day <= b["end"]]


def upcoming(feed: dict, today: date) -> list[dict]:
    day = today.isoformat()
    return sorted(
        (b for b in feed.get("banners", []) if b["start"] > day), key=lambda b: b["start"]
    )
