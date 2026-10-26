"""GET /api/planner: the daily planner's read-only game data (built as `planner.json`).

The planner itself runs on the player's device and keeps their plan there; the server never
receives or stores it. This route only serves which domains drop which materials on which
days. The build already writes released records only; serving re-checks every character and
weapon against the loaded corpus, so a stale or hand-edited file still cannot name anything
the leak gate holds back.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response

from irminsul.engine.entities import EntityStore
from irminsul.schema import ReleaseStatus

log = logging.getLogger("irminsul.planner")

CACHE_CONTROL = "public, max-age=3600"


def released_only(planner: dict[str, Any], store: EntityStore) -> dict[str, Any]:
    """Keep characters and weapons the store has as released, and only the series they use."""

    def ok(entity_id: str, kind: str) -> bool:
        match = store.by_id.get(entity_id)
        return (
            match is not None
            and match.kind == kind
            and match.entity.release.status == ReleaseStatus.RELEASED
        )

    characters = [c for c in planner.get("characters", []) if ok(c["id"], "character")]
    weapons = [w for w in planner.get("weapons", []) if ok(w["id"], "weapon")]
    books = {b for c in characters for b in c.get("books", [])}
    materials = {w["material"] for w in weapons}
    return {
        **planner,
        "books": {k: v for k, v in planner.get("books", {}).items() if k in books},
        "weapon_materials": {
            k: v for k, v in planner.get("weapon_materials", {}).items() if k in materials
        },
        "characters": characters,
        "weapons": weapons,
    }


def load_planner(data: Path, store: EntityStore) -> bytes | None:
    path = data / "planner.json"
    if not path.exists():
        log.warning("no planner data at %s: /api/planner will answer 404", path)
        return None
    planner = released_only(json.loads(path.read_text(encoding="utf-8")), store)
    return json.dumps(planner, ensure_ascii=False, separators=(",", ":")).encode()


def add_planner(app: FastAPI, store: EntityStore, data: Path) -> None:
    body = load_planner(data, store)
    etag = f'"{hashlib.sha256(body).hexdigest()[:16]}"' if body else None

    @app.get("/api/planner")
    def planner(request: Request) -> Response:
        if body is None:
            return Response(
                status_code=404,
                content=b'{"detail":"no planner data"}',
                media_type="application/json",
            )
        headers = {"Cache-Control": CACHE_CONTROL, "ETag": etag}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return Response(content=body, media_type="application/json", headers=headers)
