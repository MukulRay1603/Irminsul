"""GET /api/patches: what each game version added or changed, from official data.

Built once at startup from the loaded corpus (release timestamps), the change history
(`history.json`) and the official videos; see engine/patches.py. Released content only:
announced characters are listed by name as "officially announced", nothing more.
"""

import hashlib
import json
from pathlib import Path

from fastapi import FastAPI, Request, Response

from irminsul.pipeline.history import load_history

CACHE_CONTROL = "public, max-age=3600"


def load_patch_history(data: Path) -> dict:
    return load_history(data / "history.json")


def add_patches(app: FastAPI, notes: dict) -> None:
    body = json.dumps(notes, ensure_ascii=False, separators=(",", ":")).encode()
    etag = f'"{hashlib.sha256(body).hexdigest()[:16]}"'

    @app.get("/api/patches")
    def patches(request: Request) -> Response:
        headers = {"Cache-Control": CACHE_CONTROL, "ETag": etag}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return Response(content=body, media_type="application/json", headers=headers)
