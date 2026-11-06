"""A player's public character showcase, from a UID they choose to share in chat.

A UID is the public ID players swap to add friends. Enka.Network reads the in-game showcase,
which only holds what that player chose to display: no login and no token. Primogems, pity
and wish history are not in it. Results are kept in memory for Enka's `ttl` only; nothing is
written anywhere, and the nickname and signature are never read.
"""

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable

import httpx

from irminsul.engine.entities import EntityStore

log = logging.getLogger("irminsul.players")

API = "https://enka.network/api/uid/{}/"
USER_AGENT = "Irminsul/1.0 (+https://mukulray-irminsul.hf.space)"
MAX_CACHED = 500
LEVEL_PROP = "4001"

Fetch = Callable[[str], dict | None]


def _http(uid: str) -> dict | None:
    r = httpx.get(API.format(uid), headers={"User-Agent": USER_AGENT}, timeout=8.0)
    return r.json() if r.status_code == 200 else None


class Showcase:
    def __init__(self, store: EntityStore, fetch: Fetch | None = None, clock=time.time) -> None:
        self._fetch = fetch or _http
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
        self._names = {
            str(m.entity.game_id): m.entity.name for m in store.by_id.values() if m.entity.game_id
        }

    def _weapon(self, equip: list[dict]) -> str | None:
        for item in equip:
            if "weapon" in item:
                name = self._names.get(str(item.get("itemId")))
                refine = (next(iter(item["weapon"].get("affixMap", {}).values()), 0) or 0) + 1
                return f"{name} R{refine}" if name else None
        return None

    def characters(self, uid: str) -> list[dict] | None:
        """The showcased characters, or None if the showcase can't be read."""
        with self._lock:
            hit = self._cache.get(uid)
            if hit and self._clock() < hit[0]:
                return hit[1]
        try:
            data = self._fetch(uid)
        except Exception as e:  # Enka down, slow or under maintenance: never a 500
            log.warning("showcase fetch failed: %s", e)
            return None
        if not data:
            return None
        rows = []
        for a in data.get("avatarInfoList") or []:
            name = self._names.get(str(a.get("avatarId")))
            if not name:
                continue  # a character we can't name (or an unreleased one): skip it
            level = (a.get("propMap") or {}).get(LEVEL_PROP, {}).get("val")
            rows.append(
                {
                    "name": name,
                    "constellation": len(a.get("talentIdList") or []),
                    "level": int(level) if str(level or "").isdigit() else None,
                    "weapon": self._weapon(a.get("equipList") or []),
                }
            )
        with self._lock:
            self._cache[uid] = (self._clock() + max(60, int(data.get("ttl") or 60)), rows)
            while len(self._cache) > MAX_CACHED:
                self._cache.popitem(last=False)
        return rows


def line(c: dict) -> str:
    level = f" Lv.{c['level']}" if c["level"] else ""
    weapon = f", {c['weapon']}" if c["weapon"] else ""
    return f"{c['name']} C{c['constellation']}{level}{weapon}"
