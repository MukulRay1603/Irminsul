"""GET /api/community-videos?version=X: popular community build guides for that version.

Official videos come from HoYoWiki with the corpus. These come from the YouTube Data API,
only when someone opens the (closed by default) "Community build guides" group, so a
quiet day costs no quota. Needs YOUTUBE_API_KEY; without it the group is not offered.

Community videos are the main place leaks live, so a video is kept only if:
- it was published after the character's official release (pre-release guides are
  built on beta data),
- its title names the character and mentions no leaks, betas, datamines, unreleased
  characters or versions newer than the live game, and nothing explicit,
- it is a full video (2 minutes or more), not a Short.
The 3 most-viewed survivors per character are shown, labelled as community content.
Results are cached for a day per character, and searches are capped per day (one search
costs 100 of the free 10,000 daily units).
"""

import html
import logging
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException, Request

from irminsul.api.app import client_id
from irminsul.api.limits import Window
from irminsul.engine.entities import EntityStore
from irminsul.engine.guards import _ADULT
from irminsul.pipeline.safety import LEAK_LANGUAGE
from irminsul.schema import ReleaseStatus

log = logging.getLogger("irminsul.community")

API = "https://www.googleapis.com/youtube/v3"
TTL_S = 24 * 3600
FAILED_TTL_S = 600
RECENT_VERSIONS = 3  # the live version and the two before it; older ones: official videos only
PER_CLIENT_PER_HOUR = 30
PER_CHARACTER = 3
MIN_SECONDS = 120
SEARCHES_PER_DAY = 60  # 6,000 of the 10,000 free units, leaving room for the rest

_LEAKY = re.compile(
    r"\bleak\w*|\bbeta\b|\bdatamin\w*|\bdrip\w*|\bunreleased\b|\bupcoming\b|\bfuture\b"
    r"|\bspeculat\w*|\brumou?r\w*",
    re.I,
)
_VERSION = re.compile(r"\b(\d)\.(\d)\b")
_DURATION = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")

Fetch = Callable[[str, dict], dict]


def seconds(iso: str) -> int:
    m = _DURATION.match(iso or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


class CommunityVideos:
    def __init__(
        self,
        store: EntityStore,
        key: str,
        live: tuple[int, int] | None,
        fetch: Fetch | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store = store
        self.key = key
        self.live = live
        self._fetch = fetch or self._http
        self._clock = clock
        self._cache: dict[str, tuple[float, list[dict], bool]] = {}  # when, videos, succeeded
        self._flights: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()
        self._day = ""
        self._searches = 0
        # Names that must never appear in a kept title: characters not released yet
        self._unreleased = [
            re.compile(rf"\b{re.escape(m.entity.name)}\b", re.I)
            for m in store.by_id.values()
            if m.kind == "character" and m.entity.release.status != ReleaseStatus.RELEASED
        ]

    def _http(self, endpoint: str, params: dict) -> dict:
        r = httpx.get(f"{API}/{endpoint}", params={**params, "key": self.key}, timeout=10.0)
        r.raise_for_status()
        return r.json()

    def safe_title(self, title: str, name: str) -> bool:
        if name.lower() not in title.lower():
            return False
        if LEAK_LANGUAGE.search(title) or _LEAKY.search(title) or _ADULT.search(title):
            return False
        if any(p.search(title) for p in self._unreleased):
            return False
        versions = [(int(a), int(b)) for a, b in _VERSION.findall(title)]
        return not (self.live and any(v > self.live for v in versions))

    def _budget(self) -> bool:
        day = time.strftime("%Y-%m-%d", time.gmtime(self._clock()))
        if day != self._day:
            self._day, self._searches = day, 0
        if self._searches >= SEARCHES_PER_DAY:
            return False
        self._searches += 1
        return True

    def for_character(self, entity_id: str) -> list[dict]:
        match = self.store.by_id.get(entity_id)
        if match is None or match.kind != "character":
            return []
        c = match.entity
        released: datetime | None = c.release.released_at
        if c.release.status != ReleaseStatus.RELEASED or released is None:
            return []
        with self._lock:
            hit = self._cache.get(entity_id)
            if hit and self._clock() - hit[0] < (TTL_S if hit[1] or hit[2] else FAILED_TTL_S):
                return hit[1]
            flight = self._flights.setdefault(entity_id, threading.Lock())
        with flight:  # two players opening the same version: one search, not two
            with self._lock:
                hit = self._cache.get(entity_id)
                if hit and self._clock() - hit[0] < (TTL_S if hit[1] or hit[2] else FAILED_TTL_S):
                    return hit[1]
                if not self._budget():
                    return hit[1] if hit else []
            return self._search(entity_id, c, released)

    def _search(self, entity_id: str, c, released: datetime) -> list[dict]:
        try:
            found = self._fetch(
                "search",
                {
                    "part": "snippet",
                    "q": f"{c.name} build guide Genshin Impact",
                    "type": "video",
                    "maxResults": 15,
                    "order": "relevance",
                    "publishedAfter": released.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "relevanceLanguage": "en",
                    "safeSearch": "strict",
                    "videoEmbeddable": "true",
                },
            )
            items = [
                i
                for i in found.get("items", [])
                if i.get("id", {}).get("videoId")
                and self.safe_title(html.unescape(i.get("snippet", {}).get("title", "")), c.name)
            ]
            stats = {}
            if items:
                ids = ",".join(i["id"]["videoId"] for i in items)
                details = self._fetch("videos", {"part": "statistics,contentDetails", "id": ids})
                stats = {d["id"]: d for d in details.get("items", [])}
        except Exception as e:  # quota, network, bad key: no community videos, never a 500
            log.warning("community videos for %s failed: %s", entity_id, e)
            with self._lock:  # don't retry on every open: wait FAILED_TTL_S
                self._cache[entity_id] = (self._clock(), [], False)
            return []
        kept = []
        for i in items:
            vid = i["id"]["videoId"]
            d = stats.get(vid)
            if not d or seconds(d.get("contentDetails", {}).get("duration", "")) < MIN_SECONDS:
                continue
            sn = i["snippet"]
            kept.append(
                {
                    "entity_id": entity_id,
                    "youtube_id": vid,
                    "title": html.unescape(sn.get("title", "")),
                    "channel": html.unescape(sn.get("channelTitle", "")),
                    "published": sn.get("publishedAt", "")[:10],
                    "views": int(d.get("statistics", {}).get("viewCount", 0) or 0),
                }
            )
        kept.sort(key=lambda v: v["views"], reverse=True)
        kept = kept[:PER_CHARACTER]
        with self._lock:
            self._cache[entity_id] = (self._clock(), kept, True)
        return kept


def add_community(
    app: FastAPI, community: CommunityVideos | None, notes: dict, trusted_hops: int = 0
) -> None:
    # Newest first in the notes: only recent versions can spend search quota
    recent = notes["versions"][:RECENT_VERSIONS]
    by_version = {n["version"]: [c["id"] for c in n["characters"]] for n in recent}
    window = Window(limit=PER_CLIENT_PER_HOUR, seconds=3600)

    @app.get("/api/community-videos")
    def community_videos(version: str, request: Request) -> dict:
        if community is None:
            raise HTTPException(404)
        if version not in by_version:
            raise HTTPException(404)
        if not window.allow(client_id(request, trusted_hops)):
            raise HTTPException(429, "Too many requests. Try again later.")
        videos = [v for cid in by_version[version] for v in community.for_character(cid)]
        return {"version": version, "videos": videos}
