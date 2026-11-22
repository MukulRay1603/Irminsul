"""Team facts that re-check themselves when the game moves on.

Every team fact and build line carries the game version it was checked for. Once the live
game is newer, the build re-reads that line's source page and looks for what the line says:
its numbers and its names.
- Found: the line is re-stamped for the live version (`fact_checks.json`), no person needed.
- Not found: the line is hidden from answers. Its page is read again every week, and the line
  comes back by itself once the page says it again (or when the curated file gets a newer
  "checked" date). Nobody is asked to do anything: the counts go in the manifest.
- Page unreadable (down, blocked, or rendered only in a browser): the line keeps its own
  "checked" date, which answers already show, and is tried again on the next run.

Only lines that are behind the live version are fetched, each page once, so a version day
reads a few hundred pages and every other day reads none.
"""

import hashlib
import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import unquote, urlparse

from irminsul.sources.http import FetchError, PoliteClient

log = logging.getLogger("irminsul.recheck")

OK, UNSURE, CHANGED = "ok", "unsure", "changed"
UNREADABLE, UNCHECKABLE = "unreadable", "uncheckable"
RETRY_DAYS = 7  # a hidden line's page is read again this often, so it returns on its own
MIN_PAGE_CHARS = 500  # less than this is a shell page that needs a browser to fill it
NAME_SHARE = 0.75  # this share of a line's names must be on the page (numbers: all of them)

_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_WORD = r"[A-Z][\w'’-]*"
_NAME = re.compile(rf"{_WORD}(?:\s+(?:of the|of|the|de|to)?\s*{_WORD})*")
_VERSION = re.compile(r"\b(\d+)\.(\d+)\b")
_TAGS = re.compile(r"<(script|style|noscript|svg)\b.*?</\1>", re.I | re.S)
_ANY_TAG = re.compile(r"<[^>]+>")
# Words a line uses about itself, not about the game: never looked for on the page
NOT_NAMES = {
    "a",
    "an",
    "the",
    "in",
    "on",
    "at",
    "if",
    "it",
    "its",
    "as",
    "by",
    "for",
    "from",
    "with",
    "this",
    "that",
    "these",
    "those",
    "each",
    "every",
    "one",
    "two",
    "all",
    "any",
    "some",
    "you",
    "your",
    "they",
    "their",
    "when",
    "while",
    "once",
    "after",
    "before",
    "both",
    "only",
    "also",
    "but",
    "or",
    "and",
    "not",
    "no",
    "use",
    "best",
    "good",
    "great",
    "then",
    "official",
    "officially",
    "estimate",
    "community",
    "hoyoverse",
    "hoyoverse's",
    "kqm",
    "version",
    "versions",
    "patch",
    "update",
    "notice",
    "notices",
    "page",
    "guide",
    "wiki",
    "game8",
    "fandom",
    "genshin",
    "impact",
    "genshin impact",
    "hoyolab",
    "q&a",
    "faq",
}


@dataclass
class Line:
    fact: str
    url: str
    checked: str  # the date the team checked it by hand
    version: str  # the version text from the file, e.g. "7.1" or "7.1 (since 5.0)"

    @property
    def key(self) -> str:
        return hashlib.sha1(f"{self.url}\n{self.fact}".encode()).hexdigest()[:16]


def _older_than(day: str, now: datetime, days: int) -> bool:
    return (now.date() - datetime.fromisoformat(day).date()).days >= days


def newest_version(text: str) -> tuple[int, int] | None:
    found = [(int(a), int(b)) for a, b in _VERSION.findall(text)]
    return max(found) if found else None


def behind(line: Line, live: tuple[int, int] | None) -> bool:
    """True when the line was checked for an older version than the live one."""
    newest = newest_version(line.version)
    return bool(live and newest and newest < live)


# ---- what a line says ---------------------------------------------------------------------
def _norm(text: str) -> str:
    text = html.unescape(text).replace("’", "'").replace("‘", "'").replace("\u00a0", " ")
    return " ".join(text.split()).casefold()


def _numbers(text: str) -> set[float]:
    return {float(raw.replace(",", "")) for raw in _NUMBER.findall(text)}


# Other sources a line may quote beside its own page: (word in the line, host of that source)
OTHER_SOURCES = (
    ("yatta", "yatta.moe"),
    ("hoyowiki", "wiki.hoyolab.com"),
    ("game8", "game8.co"),
    ("fandom", "fandom.com"),
    ("kqm", "keqingmains.com"),
)
# "(2.1 Moonlight Merriment)", "Version 3.1 event": when an item came out, not what it does
_EVENT_VERSION = re.compile(
    r"\b(?:version\s+)?\d\.\d\b(?=[^.;,)]*\bevent\b)|version\s+\d\.\d", re.I
)


def _own_clauses(fact: str, url: str) -> list[str]:
    """The parts of a line its own page should say: a clause that credits another source
    ("a six-way tie in Yatta's weapon data") is that source's to confirm, not this page's."""
    host = urlparse(url).hostname or ""
    others = [w for w, h in OTHER_SOURCES if not host.endswith(h)]
    clauses = re.split(r"[;()]|,\s|(?<=[.!?])\s+", fact)  # "1,600" stays one number
    return [c for c in clauses if not any(w in c.casefold() for w in others)]


def terms(fact: str, url: str = "") -> tuple[set[float], list[str]]:
    """The numbers (10 and up, or with decimals) and the proper names a line states."""
    numbers: set[float] = set()
    names: list[str] = []
    for clause in _own_clauses(fact, url):
        numbers |= {n for n in _numbers(_EVENT_VERSION.sub(" ", clause)) if n >= 10 or n != int(n)}
        words = clause.strip()
        for m in _NAME.finditer(words):
            name = m.group(0).strip(" '’-")
            # A capital at the very start of a clause says nothing: "Every", "Either Fate"
            words_in = name.split()[1:] if m.start() == 0 else name.split()
            while words_in and words_in[0].casefold() in NOT_NAMES:
                words_in.pop(0)  # "On the Weapon Event Wish" is about the "Weapon Event Wish"
            name = " ".join(words_in).removesuffix("'s").removesuffix("’s")
            parts = [p for p in words_in if p.casefold() not in NOT_NAMES]
            if not parts or name.casefold() in NOT_NAMES or len(name) < 3:
                continue
            if name.casefold() not in {n.casefold() for n in names}:
                names.append(name)
    return numbers, names


def verdict(fact: str, page: str, url: str = "") -> tuple[str, list[str]]:
    """(status, what's missing) for one line against its page's text.

    A missing number is a CHANGED line: numbers are what a fact is for, and a page that no
    longer shows them has moved on. Missing names alone are UNSURE: pages reword more than
    they renumber, so the line stays up and is listed for a look.
    """
    numbers, names = terms(fact, url)
    if not numbers and not names:
        return UNCHECKABLE, []
    text = _norm(page)
    found_numbers = _numbers(text)
    missing = [f"{n:g}" for n in sorted(numbers) if n not in found_numbers]

    words = set(re.findall(r"[\w'+%-]+", text))

    def on_page(name: str) -> bool:
        """The name as written, or else every word of it (a line says "CRIT DMG Circlet" for a
        page's "Circlet: CRIT DMG")."""
        n = _norm(name)
        if n in text or n.removesuffix("s") in text:
            return True
        parts = [w.removesuffix("'s") for w in n.split() if w not in NOT_NAMES]
        return bool(parts) and all(w in words or w.removesuffix("s") in words for w in parts)

    absent = [name for name in names if not on_page(name)]
    names_ok = not names or (len(names) - len(absent)) / len(names) >= NAME_SHARE
    if missing:
        return CHANGED, missing + absent
    if not names_ok:
        return UNSURE, absent
    return OK, []


# ---- reading a page -----------------------------------------------------------------------
NOTICE_API = "https://sg-public-api.hoyoverse.com/content_v2_user/app/a1b1f9d3315447cc/getContent"
WIKI_API = "https://sg-wiki-api-static.hoyolab.com/hoyowiki/genshin/wapi/entry_page"
POST_API = "https://bbs-api-os.hoyolab.com/community/post/wapi/getPostFull"
WIKI_HEADERS = {"x-rpc-language": "en-us", "Referer": "https://wiki.hoyolab.com/"}


def html_text(page: str) -> str:
    return " ".join(_ANY_TAG.sub(" ", _TAGS.sub(" ", page)).split())


def _strings(value) -> list[str]:
    """Every string inside a JSON value (the official APIs nest text several levels deep)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def read(url: str, client: PoliteClient) -> str | None:
    """The readable text of a source page, or None when there's nothing to read."""
    u = urlparse(url)
    host, path = (u.hostname or "").removeprefix("www."), u.path
    if host == "genshin.hoyoverse.com" and (m := re.search(r"/news/detail/(\d+)", path)):
        data = client.get_json(NOTICE_API, {"iAppId": 32, "iInfoId": m[1], "sLangKey": "en-us"})
        text = ((data or {}).get("data") or {}).get("sContent", "")
    elif host == "wiki.hoyolab.com" and (m := re.search(r"/entry/(\d+)", path)):
        data = client.get_json(WIKI_API, {"entry_page_id": m[1]})
        text = " ".join(_strings(((data or {}).get("data") or {}).get("page", {})))
    elif host == "hoyolab.com" and (m := re.search(r"/article/(\d+)", path)):
        data = client.get_json(POST_API, {"post_id": m[1], "read": 1})
        post = (((data or {}).get("data") or {}).get("post") or {}).get("post") or {}
        text = post.get("content", "") + " " + post.get("structured_content", "")
    elif host.endswith("fandom.com") and path.startswith("/wiki/"):
        # The wiki's own API: its pages refuse plain fetches
        title = unquote(path.removeprefix("/wiki/")).replace("_", " ")
        data = client.get_json(
            f"https://{u.hostname}/api.php",
            {
                "action": "parse",
                "page": title,
                "prop": "wikitext",
                "format": "json",
                "formatversion": 2,
                "redirects": 1,
            },
        )
        text = ((data or {}).get("parse") or {}).get("wikitext", "")
    else:
        page = client.get_page(url)
        if page is None:
            return None
        text = page
    text = html_text(text)
    return text if len(text) >= MIN_PAGE_CHARS else None


# ---- the whole check ----------------------------------------------------------------------
def recheck(
    lines: list[Line],
    previous: dict,
    live: tuple[int, int] | None,
    now: datetime,
    client: PoliteClient | None,
) -> dict:
    """The new `fact_checks.json`: one verdict per line that is behind the live version.

    A verdict made for the live version is kept without fetching again, unless it says the page
    was unreadable (tried again every run). A line the team re-checked by hand after the
    machine's verdict starts over from that date.
    """
    if live is None:
        return previous or {"facts": {}}
    version = f"{live[0]}.{live[1]}"
    old = (previous or {}).get("facts", {})
    facts: dict[str, dict] = {}
    pages: dict[str, str | None] = {}
    for line in lines:
        if not behind(line, live):
            continue  # checked by hand for this version (or the file names no version)
        before = old.get(line.key)
        if (
            before
            and before.get("version") == version
            and before.get("status") != UNREADABLE
            and before.get("on", "") >= line.checked
            and not (before.get("status") == CHANGED and _older_than(before["on"], now, RETRY_DAYS))
        ):
            facts[line.key] = before
            continue
        if client is None:
            if before:
                facts[line.key] = before
            continue
        if line.url not in pages:
            try:
                pages[line.url] = read(line.url, client)
            except (FetchError, ValueError, KeyError, TypeError) as exc:
                log.warning("can't read %s: %s", line.url, exc)
                pages[line.url] = None
        page = pages[line.url]
        if page is None:
            status, missing = UNREADABLE, []
        else:
            status, missing = verdict(line.fact, page, line.url)
        facts[line.key] = {
            "status": status,
            "version": version,
            "on": now.date().isoformat(),
            "url": line.url,
            "since": (before or {}).get("since")
            if status == (before or {}).get("status")
            else now.date().isoformat(),
        }
        if missing:
            facts[line.key]["missing"] = missing[:8]
    counts: dict[str, int] = {}
    for f in facts.values():
        counts[f["status"]] = counts.get(f["status"], 0) + 1
    return {"live": version, "checked_at": now.isoformat(), "counts": counts, "facts": facts}
