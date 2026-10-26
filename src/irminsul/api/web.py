"""The player-facing web app: static files from `web/` plus the read-only data routes it uses.

- GET /                    the app (web/index.html); /static/... serves its CSS and JS
- GET /results             public test results (web/results.html + static/results.json)
- GET /manifest.webmanifest, /sw.js, /favicon.ico   what makes it an installable app
- GET /api/characters      released characters for the gallery (the leak gate decides who)
- GET /api/entity?id=...   one character, weapon or artifact set, with official videos and art
- GET /art/{key}?w=N       resized WebP art (see art.py): from a local library (IRMINSUL_ART)
                           or official images fetched and cached by the server. The artwork
                           belongs to HoYoverse and is never committed.

The page has no inline script or style, so it runs under the API's strict CSP unchanged.
"""

import hashlib
import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from irminsul.api.art import LocalArt, RemoteArt
from irminsul.engine.entities import EntityStore

log = logging.getLogger("irminsul.web")

WEB_DIR = Path(__file__).resolve().parents[3] / "web"


def load_videos(data: Path) -> dict[str, list[dict]]:
    videos: dict[str, list[dict]] = {}
    path = data / "videos.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            v = json.loads(line)
            videos.setdefault(v["entity_id"], []).append(v)
    return videos


def web_version(web_dir: Path) -> str:
    """A short hash of every file in web/: a deploy that changes any of them renames the cache."""
    h = hashlib.sha256()
    for path in sorted(p for p in web_dir.rglob("*") if p.is_file()):
        h.update(path.relative_to(web_dir).as_posix().encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:12]


def add_web(
    app: FastAPI,
    store: EntityStore,
    videos: dict[str, list[dict]],
    art: LocalArt | RemoteArt,
    web_dir: Path = WEB_DIR,
) -> None:
    if (web_dir / "index.html").exists():
        app.mount("/static", StaticFiles(directory=web_dir / "static"), name="static")

        page = (web_dir / "index.html").read_text(encoding="utf-8")
        # Link previews need an absolute image URL; set IRMINSUL_PUBLIC_URL on the deploy.
        if public_url := os.environ.get("IRMINSUL_PUBLIC_URL", "").rstrip("/"):
            page = page.replace(
                'content="/static/icons/og.png"', f'content="{public_url}/static/icons/og.png"'
            )
        worker = (
            (web_dir / "sw.js")
            .read_text(encoding="utf-8")
            .replace("__VERSION__", web_version(web_dir))
        )
        fresh = {"Cache-Control": "no-cache"}

        @app.get("/", include_in_schema=False)
        def index():
            return HTMLResponse(page, headers=fresh)

        @app.get("/results", include_in_schema=False)
        def results():
            """Public test results (web/static/results.json, made by irminsul-report)."""
            return FileResponse(web_dir / "results.html", headers=fresh)

        @app.get("/manifest.webmanifest", include_in_schema=False)
        def manifest():
            return FileResponse(
                web_dir / "manifest.webmanifest",
                media_type="application/manifest+json",
                headers=fresh,
            )

        @app.get("/sw.js", include_in_schema=False)
        def service_worker():
            # The worker lives at the root so it can serve the page; browsers re-check it often.
            return Response(
                worker,
                media_type="text/javascript",
                headers={**fresh, "Service-Worker-Allowed": "/"},
            )

        @app.get("/favicon.ico", include_in_schema=False)
        def favicon():
            return FileResponse(
                web_dir / "static" / "icons" / "favicon-32.png", media_type="image/png"
            )
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
            out.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "element": c.element,
                    "rarity": c.rarity,
                    "weapon_type": c.weapon_type,
                    "region": c.region,
                    "card": art.card(c),
                    "element_icon": art.element(c.element),
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
            c = match.entity
            # Full art only for released characters, the same rule the leak gate uses for text.
            ok = released(match)
            data["art"] = art.icon(c)
            data["splash"] = art.splash(c) if ok else None
            data["banner"] = art.banner(c) if ok else None
            data["element_icon"] = art.element(c.element)
            data.pop("namecard", None)
            for t, url in zip(data["talents"], art.talents(c), strict=True):
                t["icon"] = url
            for x, url in zip(data["constellations"], art.constellations(c), strict=True):
                x["icon"] = url
        else:
            data["art"] = art.item(match.entity) if released(match) else None
        data.pop("icon", None)  # an asset name; the URLs above are what the page uses
        return data

    @app.get("/art/{path:path}", include_in_schema=False)
    def art_file(path: str, w: int = 256):
        return FileResponse(
            art.file(path, w),
            media_type="image/webp",
            headers={"Cache-Control": "public, max-age=604800"},
        )
