"""Character, weapon and artifact art for the web app, served as resized WebP under /art/.

Two modes, chosen by irminsul-serve:

- LocalArt: a library on disk laid out as Characters/<Name>/... (IRMINSUL_ART, Ray's PC).
- RemoteArt: the official images the game data already comes from (gi.yatta.moe, with
  enka.network as a fallback), fetched on first use, resized and kept in a disk cache.
  Only asset names stored on our own records can be fetched, never a URL from a request,
  and only for released entities: an announced character never gets art.

The artwork belongs to HoYoverse. It is never committed; it lives only in the server cache.
"""

import io
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from irminsul.engine.entities import EntityStore
from irminsul.schema import Character, ReleaseStatus
from irminsul.sources.http import USER_AGENT

log = logging.getLogger("irminsul.art")

ART_WIDTHS = (64, 128, 256, 420, 900)  # never upscaled
TALENT_PREFIX = {
    "normal_attack": "Normal Attack",
    "skill": "Skill",
    "burst": "Burst",
    "passive": "Passive",
}
YATTA_UI = "https://gi.yatta.moe/assets/UI/"
ENKA_UI = "https://enka.network/ui/"
ELEMENT_ASSETS = {  # our element name -> the game's
    "Pyro": "Fire",
    "Hydro": "Water",
    "Anemo": "Wind",
    "Electro": "Electric",
    "Dendro": "Grass",
    "Cryo": "Ice",
    "Geo": "Rock",
}
MAX_BYTES = 12 * 1024 * 1024  # the largest official splash is a few MB


def _key(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def _resize(src: Path, out: Path, w: int) -> None:
    from PIL import Image  # only needed when art is configured

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    with Image.open(src) as im:
        im = im.convert("RGBA")
        if im.width > w:
            im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
        # method=6 took ~17s on a 2048px splash with alpha, method=4 under 1s at the same size
        im.save(tmp, "WEBP", quality=82, method=4)
    os.replace(tmp, out)  # readers never see a half-written file


class LocalArt:
    """Maps entities to art URLs in a local library laid out as Characters/<Name>/..."""

    def __init__(self, library: Path | None, cache: Path) -> None:
        self.library = library if library and library.is_dir() else None
        self.cache = cache

    def url(self, rel: str, w: int = 256) -> str | None:
        if self.library is None or not (self.library / rel).exists():
            return None
        return f"/art/{quote(rel)}?w={w}"

    def folder(self, name: str) -> str:
        """ "Traveler (Cryo)" has its own folder; other variants fall back to the base name."""
        if self.library and (self.library / "Characters" / name).exists():
            return name
        return name.split(" (")[0]

    def icons(self, folder: str, sub: str) -> dict[str, str]:
        """Icon URLs keyed by normalised "<prefix><name>", e.g. "skilltranscendencebalefulomen"."""
        base = self.library / "Characters" / folder / sub if self.library else None
        if base is None or not base.exists():
            return {}
        return {
            _key(p.stem.replace(" - ", "")): self.url(f"Characters/{folder}/{sub}/{p.name}", 128)
            for p in base.glob("*.png")
        }

    def _char(self, c: Character, file: str, w: int) -> str | None:
        return self.url(f"Characters/{self.folder(c.name)}/{file}", w)

    def card(self, c: Character) -> str | None:
        return self._char(c, "card.png", 256)

    def icon(self, c: Character) -> str | None:
        return self._char(c, "icon.png", 256)

    def splash(self, c: Character) -> str | None:
        return self._char(c, "splash.png", 900)

    def banner(self, c: Character) -> str | None:
        return self._char(c, "namecard_banner.png", 420)

    def element(self, element: str) -> str | None:
        return self.url(f"Elements/{element}.png", 64)

    def talents(self, c: Character) -> list[str | None]:
        icons = self.icons(self.folder(c.name), "talents")
        return [icons.get(_key(TALENT_PREFIX.get(t.kind, "") + t.name)) for t in c.talents]

    def constellations(self, c: Character) -> list[str | None]:
        icons = self.icons(self.folder(c.name), "constellations")
        return [icons.get(_key(f"C{x.level}{x.name}")) for x in c.constellations]

    def item(self, entity) -> str | None:
        return None  # the library's weapon and artifact files aren't keyed by entity id

    def file(self, path: str, w: int) -> Path:
        if self.library is None or w not in ART_WIDTHS:
            raise HTTPException(404)
        target = (self.library / path).resolve()
        if self.library.resolve() not in target.parents or target.suffix.lower() != ".png":
            raise HTTPException(404)
        if not target.exists():
            raise HTTPException(404)
        out = self.cache / f"w{w}" / Path(path).with_suffix(".webp")
        if not out.exists() or out.stat().st_mtime < target.stat().st_mtime:
            _resize(target, out, w)
        return out


Fetch = Callable[[str], bytes | None]


class RemoteArt:
    """Official images by safe key, e.g. /art/c/furina/splash?w=900, fetched once and cached.

    Keys: c/<slug>/{icon,card,splash,banner,talent-<i>,cons-<n>}, w/<slug>/icon,
    a/<slug>/icon and e/<Element>. A key resolves only to an asset name on one of our
    released records, which is fetched from a fixed host, so nothing else can be proxied.
    """

    def __init__(
        self,
        store: EntityStore,
        cache: Path,
        fetch: Fetch | None = None,
        min_interval_s: float = 0.1,
        max_parallel: int = 4,
        retry_after_s: float = 600.0,
    ) -> None:
        self.store = store
        self.cache = cache
        self._fetch = fetch or self._http_get
        self._client: httpx.Client | None = None
        self.min_interval_s = min_interval_s
        self.retry_after_s = retry_after_s
        self._parallel = threading.BoundedSemaphore(max_parallel)
        self._pace = threading.Lock()
        self._last = 0.0
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._failed: dict[str, float] = {}  # asset name -> when it may be tried again

    # --- URLs for the API ------------------------------------------------------------

    def _url(self, key: str, asset: str | None, w: int) -> str | None:
        return f"/art/{key}?w={w}" if asset else None

    def _slug(self, c) -> str:
        return c.id.split("/", 1)[1]

    def card(self, c: Character) -> str | None:
        return self._url(f"c/{self._slug(c)}/card", c.icon, 256)

    def icon(self, c: Character) -> str | None:
        return self._url(f"c/{self._slug(c)}/icon", c.icon, 256)

    def splash(self, c: Character) -> str | None:
        return self._url(f"c/{self._slug(c)}/splash", c.icon, 900)

    def banner(self, c: Character) -> str | None:
        return self._url(f"c/{self._slug(c)}/banner", c.namecard, 420)

    def element(self, element: str) -> str | None:
        return self._url(f"e/{element}", ELEMENT_ASSETS.get(element), 64)

    def talents(self, c: Character) -> list[str | None]:
        return [
            self._url(f"c/{self._slug(c)}/talent-{i}", t.icon, 128) for i, t in enumerate(c.talents)
        ]

    def constellations(self, c: Character) -> list[str | None]:
        return [
            self._url(f"c/{self._slug(c)}/cons-{x.level}", x.icon, 128) for x in c.constellations
        ]

    def item(self, entity) -> str | None:
        kind = {"weapon": "w", "artifact": "a"}.get(entity.id.split("/", 1)[0])
        return self._url(f"{kind}/{self._slug(entity)}/icon", entity.icon, 256) if kind else None

    # --- resolving a key -------------------------------------------------------------

    def resolve(self, path: str) -> tuple[str, list[str]] | None:
        """(asset name, upstream URLs to try in order) for a key, or None if it isn't one."""
        parts = path.split("/")
        if len(parts) == 2 and parts[0] == "e" and parts[1] in ELEMENT_ASSETS:
            return self._sources(f"UI_Buff_Element_{ELEMENT_ASSETS[parts[1]]}")
        if len(parts) != 3:
            return None
        prefix, slug, kind = parts
        entity_kind = {"c": "character", "w": "weapon", "a": "artifact"}.get(prefix)
        match = self.store.by_id.get(f"{entity_kind}/{slug}") if entity_kind else None
        if match is None or match.entity.release.status != ReleaseStatus.RELEASED:
            return None  # unknown, or not released: no art, the same rule as the leak gate
        e = match.entity
        if prefix == "w" and kind == "icon":
            return self._sources(e.icon)
        if prefix == "a" and kind == "icon":
            return self._sources(e.icon, "reliquary/")
        if prefix != "c":
            return None
        name = e.icon or ""
        base = name.removeprefix("UI_AvatarIcon_") if name.startswith("UI_AvatarIcon_") else ""
        if kind == "icon":
            return self._sources(e.icon)
        if kind == "card":
            return self._sources(f"{name}_Card" if name else None)
        if kind == "splash":
            return self._sources(f"UI_Gacha_AvatarImg_{base}" if base else None)
        if kind == "banner" and e.namecard and "NameCardIcon" in e.namecard:
            return self._sources(
                e.namecard.replace("NameCardIcon", "NameCardPic") + "_P", "namecard/"
            )
        index = kind.partition("-")[2]
        if not index.isdigit() or len(index) > 2:
            return None
        if kind.startswith("talent-") and int(index) < len(e.talents):
            return self._sources(e.talents[int(index)].icon)
        if kind.startswith("cons-"):
            cons = [x for x in e.constellations if x.level == int(index)]
            return self._sources(cons[0].icon) if cons else None
        return None

    def _sources(self, name: str | None, yatta_dir: str = "") -> tuple[str, list[str]] | None:
        # Names come from our own records, but check once more that they can't change the path
        if not name or not name.replace("_", "").isalnum() or not name.isascii():
            return None
        return name, [f"{YATTA_UI}{yatta_dir}{name}.png", f"{ENKA_UI}{name}.png"]

    # --- serving ---------------------------------------------------------------------

    def file(self, path: str, w: int) -> Path:
        if w not in ART_WIDTHS:
            raise HTTPException(404)
        resolved = self.resolve(path)
        if resolved is None:
            raise HTTPException(404)
        name, sources = resolved
        out = self.cache / f"w{w}" / f"{name}.webp"
        if out.exists():
            return out
        with self._lock(name):  # one fetch and one resize per image, however many ask
            if out.exists():
                return out
            src = self._original(name, sources)
            if src is None:
                raise HTTPException(404)
            _resize(src, out, w)
        return out

    def _lock(self, name: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(name, threading.Lock())

    def _original(self, name: str, sources: list[str]) -> Path | None:
        src = self.cache / "src" / f"{name}.png"
        if src.exists():
            return src
        if self._failed.get(name, 0.0) > time.monotonic():
            return None  # failed recently: don't ask upstream again on every page view
        for url in sources:
            data = self._get(url)
            if data and _is_image(data):
                src.parent.mkdir(parents=True, exist_ok=True)
                tmp = src.with_suffix(f".{os.getpid()}.tmp")
                tmp.write_bytes(data)
                os.replace(tmp, src)
                return src
        log.info("no art for %s from %d sources", name, len(sources))
        self._failed[name] = time.monotonic() + self.retry_after_s
        return None

    def _get(self, url: str) -> bytes | None:
        with self._parallel:
            with self._pace:  # at most one upstream request per min_interval_s
                wait = self._last + self.min_interval_s - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                self._last = time.monotonic()
            try:
                return self._fetch(url)
            except Exception as e:  # any failure means "no image", never a 500
                log.warning("art fetch failed for %s: %s", url, e)
                return None

    def _http_get(self, url: str) -> bytes | None:
        if self._client is None:
            self._client = httpx.Client(
                headers={"User-Agent": USER_AGENT}, timeout=10.0, follow_redirects=False
            )
        with self._client.stream("GET", url) as resp:
            if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith(
                "image/"
            ):
                return None
            data = bytearray()
            for chunk in resp.iter_bytes():
                data += chunk
                if len(data) > MAX_BYTES:
                    return None
            return bytes(data)


def _is_image(data: bytes) -> bool:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        return True
    except Exception:
        return False
