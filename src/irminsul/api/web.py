"""The player-facing web app: static files from `web/` plus the read-only data routes it uses.

- GET /                    the app (web/index.html); /static/... serves its CSS and JS
- GET /results             public test results (web/results.html + static/results.json)
- GET /api/characters      released characters for the gallery (the leak gate decides who)
- GET /api/entity?id=...   one character, weapon or artifact set, with official videos and art
- GET /art/{path}?w=N      resized WebP art, only when IRMINSUL_ART points at a local art
                           library. The artwork belongs to HoYoverse and is never committed.

The page has no inline script or style, so it runs under the API's strict CSP unchanged.
"""

import json
import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from irminsul.engine.entities import EntityStore

log = logging.getLogger("irminsul.web")

WEB_DIR = Path(__file__).resolve().parents[3] / "web"
ART_WIDTHS = (64, 128, 256, 420, 900)  # never upscaled
TALENT_PREFIX = {
    "normal_attack": "Normal Attack",
    "skill": "Skill",
    "burst": "Burst",
    "passive": "Passive",
}


def _key(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


class Art:
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

    def render(self, path: str, w: int) -> Path:
        if self.library is None or w not in ART_WIDTHS:
            raise HTTPException(404)
        target = (self.library / path).resolve()
        if self.library.resolve() not in target.parents or target.suffix.lower() != ".png":
            raise HTTPException(404)
        if not target.exists():
            raise HTTPException(404)
        out = self.cache / f"w{w}" / Path(path).with_suffix(".webp")
        if not out.exists() or out.stat().st_mtime < target.stat().st_mtime:
            from PIL import Image  # only needed when an art library is configured

            out.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(target) as im:
                im = im.convert("RGBA")
                if im.width > w:
                    im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
                im.save(out, "WEBP", quality=82, method=6)
        return out


def load_videos(data: Path) -> dict[str, list[dict]]:
    videos: dict[str, list[dict]] = {}
    path = data / "videos.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            v = json.loads(line)
            videos.setdefault(v["entity_id"], []).append(v)
    return videos


def add_web(
    app: FastAPI,
    store: EntityStore,
    videos: dict[str, list[dict]],
    art: Art,
    web_dir: Path = WEB_DIR,
) -> None:
    if (web_dir / "index.html").exists():
        app.mount("/static", StaticFiles(directory=web_dir / "static"), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(web_dir / "index.html", headers={"Cache-Control": "no-cache"})

        @app.get("/results", include_in_schema=False)
        def results():
            """Public test results (web/static/results.json, made by irminsul-report)."""
            return FileResponse(web_dir / "results.html", headers={"Cache-Control": "no-cache"})
    else:
        log.warning("no web app at %s: serving the API only", web_dir)

    def released(match) -> bool:
        return match.kind != "character" or match.entity.release.status == "released"

    @app.get("/api/characters")
    def characters() -> list[dict]:
        """Released characters only: the gallery never shows anyone the leak gate holds back."""
        out = []
        for match in store.by_id.values():
            c = match.entity
            if match.kind != "character" or not released(match):
                continue
            folder = art.folder(c.name)
            out.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "element": c.element,
                    "rarity": c.rarity,
                    "weapon_type": c.weapon_type,
                    "region": c.region,
                    "card": art.url(f"Characters/{folder}/card.png"),
                    "element_icon": art.url(f"Elements/{c.element}.png", 64),
                    "released_at": c.release.released_at.isoformat()
                    if c.release.released_at
                    else None,
                }
            )
        out.sort(key=lambda c: c["released_at"] or "", reverse=True)
        return out

    @app.get("/api/entity")
    def entity(id: str) -> dict:
        match = store.by_id.get(id)
        if match is None:
            raise HTTPException(404, "unknown entity")
        data = match.entity.model_dump(mode="json")
        data["kind"] = match.kind
        own = [v for v in videos.get(id, []) if v["group"] == "Character Details"]
        data["videos"] = own[:6]
        if match.kind == "character":
            folder = art.folder(match.entity.name)
            # Full art only for released characters, the same rule the leak gate uses for text.
            ok = released(match)
            data["art"] = art.url(f"Characters/{folder}/icon.png", 256)
            data["splash"] = art.url(f"Characters/{folder}/splash.png", 900) if ok else None
            data["banner"] = (
                art.url(f"Characters/{folder}/namecard_banner.png", 420) if ok else None
            )
            data["element_icon"] = art.url(f"Elements/{match.entity.element}.png", 64)
            talents = art.icons(folder, "talents")
            for t in data["talents"]:
                t["icon"] = talents.get(_key(TALENT_PREFIX.get(t["kind"], "") + t["name"]))
            cons = art.icons(folder, "constellations")
            for c in data["constellations"]:
                c["icon"] = cons.get(_key(f"C{c['level']}{c['name']}"))
        return data

    @app.get("/art/{path:path}", include_in_schema=False)
    def art_file(path: str, w: int = 256):
        return FileResponse(
            art.render(path, w),
            media_type="image/webp",
            headers={"Cache-Control": "public, max-age=604800"},
        )
