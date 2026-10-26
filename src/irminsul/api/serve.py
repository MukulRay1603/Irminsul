"""Start the API: load the corpus + index, wire the engine, run uvicorn.

Data comes from local folders, or is downloaded once at boot from the public HF Dataset:
    IRMINSUL_DATA=data/build IRMINSUL_INDEX=data/index uv run irminsul-serve
    IRMINSUL_HF_DATASET=MukulRay/irminsul-corpus uv run irminsul-serve   # e.g. on a Space
LLM keys (GROQ_API_KEY, ...) are read from the environment; without any, the API still
serves exact answers and refusals, and LLM questions get a "busy" reply.
IRMINSUL_KQM=off keeps KQM-derived chunks out of every answer (see kqm_enabled).
Security settings (docs/security.md):
    IRMINSUL_TRUSTED_PROXY_HOPS=1    on HF Spaces, so limits key on the real client address
    IRMINSUL_CORS_ORIGINS=https://a.example,https://b.example   (default: no CORS)
    IRMINSUL_FRAME_ANCESTORS="https://huggingface.co"   to allow the Space page to embed it
    IRMINSUL_MAX_CONCURRENCY=64      requests in flight before uvicorn answers 503
"""

import json
import logging
import os
from pathlib import Path

import uvicorn

from irminsul.api.app import cors_origins, create_app, trusted_proxy_hops
from irminsul.api.limits import Limits
from irminsul.api.planner import add_planner
from irminsul.api.web import Art, add_web, load_videos
from irminsul.engine.engine import Engine
from irminsul.engine.entities import EntityStore
from irminsul.engine.guards import GuardConfig, version_from_manifest
from irminsul.engine.llm import Router

log = logging.getLogger("irminsul.serve")


def fetch_dataset(repo: str, dest: Path) -> Path:
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(repo, repo_type="dataset", local_dir=dest))


def kqm_enabled() -> bool:
    """KQM (CC BY-NC-SA) content is on unless IRMINSUL_KQM is off/0/false/no.

    The switch is a deploy setting, so a commercial build can drop KQM without a rebuild.
    """
    return os.environ.get("IRMINSUL_KQM", "on").strip().lower() not in {"off", "0", "false", "no"}


def build_app():
    data = Path(os.environ.get("IRMINSUL_DATA", "data/build"))
    index_dir = Path(os.environ.get("IRMINSUL_INDEX", "data/index"))
    if repo := os.environ.get("IRMINSUL_HF_DATASET"):
        root = fetch_dataset(repo, Path(os.environ.get("IRMINSUL_CACHE", "/tmp/irminsul")))
        data, index_dir = root, root / "index"
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    yatta_version = manifest.get("sources", {}).get("yatta", {}).get("game_version")
    live = version_from_manifest(yatta_version)
    guard_cfg = GuardConfig(live, (live[0], live[1] + 1)) if live else GuardConfig()

    index = None
    if (index_dir / "meta.json").exists():
        from irminsul.retrieval.index import HybridIndex

        index = HybridIndex.load(index_dir)
    else:
        log.warning("no index at %s: only exact answers and refusals will work", index_dir)

    kqm = kqm_enabled()
    if not kqm:
        log.info("KQM content is switched off (IRMINSUL_KQM): answers use official + team tiers")
    engine = Engine(
        EntityStore.load(data),
        index,
        Router.from_config(),
        guard_cfg,
        exclude_tiers=frozenset() if kqm else frozenset({"kqm"}),
    )
    meta = {
        "built_at": manifest.get("built_at"),
        "game_version": yatta_version,
        "docs": manifest.get("docs"),
        "kqm": kqm,
    }
    limits = Limits(
        per_minute=int(os.environ.get("IRMINSUL_PER_MINUTE", 6)),
        per_day=int(os.environ.get("IRMINSUL_PER_DAY", 200)),
        llm_per_day=int(os.environ.get("IRMINSUL_LLM_PER_DAY", 500)),
        allowance_cap=int(os.environ.get("IRMINSUL_ALLOWANCE_CAP", 20)),
        allowance_regen_s=60 * int(os.environ.get("IRMINSUL_ALLOWANCE_REGEN_MIN", 30)),
    )
    app = create_app(
        engine,
        limits,
        meta,
        trusted_hops=trusted_proxy_hops(),
        cors=cors_origins(),
        frame_ancestors=os.environ.get("IRMINSUL_FRAME_ANCESTORS", "'none'"),
    )
    library = os.environ.get("IRMINSUL_ART")  # local art library; never part of the repo
    cache = Path(os.environ.get("IRMINSUL_CACHE", "/tmp/irminsul")) / "art"
    add_web(app, engine.store, load_videos(data), Art(Path(library) if library else None, cache))
    add_planner(app, engine.store, data)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        build_app(),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", 7860)),
        # X-Forwarded-For is handled by client_id (IRMINSUL_TRUSTED_PROXY_HOPS), not uvicorn.
        proxy_headers=False,
        server_header=False,
        limit_concurrency=int(os.environ.get("IRMINSUL_MAX_CONCURRENCY", 64)),
    )


if __name__ == "__main__":
    main()
