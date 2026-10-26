"""Start the API: load the corpus + index, wire the engine, run uvicorn.

Data comes from local folders, or is downloaded once at boot from the public HF Dataset:
    IRMINSUL_DATA=data/build IRMINSUL_INDEX=data/index uv run irminsul-serve
    IRMINSUL_HF_DATASET=MukulRay/irminsul-corpus uv run irminsul-serve   # e.g. on a Space
LLM keys (GROQ_API_KEY, ...) are read from the environment; without any, the API still
serves exact answers and refusals, and LLM questions get a "busy" reply.
"""

import json
import logging
import os
from pathlib import Path

import uvicorn

from irminsul.api.app import create_app
from irminsul.api.limits import Limits
from irminsul.engine.engine import Engine
from irminsul.engine.entities import EntityStore
from irminsul.engine.guards import GuardConfig, version_from_manifest
from irminsul.engine.llm import Router

log = logging.getLogger("irminsul.serve")


def fetch_dataset(repo: str, dest: Path) -> Path:
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(repo, repo_type="dataset", local_dir=dest))


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

    engine = Engine(EntityStore.load(data), index, Router.from_config(), guard_cfg)
    meta = {
        "built_at": manifest.get("built_at"),
        "game_version": yatta_version,
        "docs": manifest.get("docs"),
    }
    limits = Limits(
        per_minute=int(os.environ.get("IRMINSUL_PER_MINUTE", 6)),
        per_day=int(os.environ.get("IRMINSUL_PER_DAY", 60)),
        llm_per_day=int(os.environ.get("IRMINSUL_LLM_PER_DAY", 1500)),
    )
    return create_app(engine, limits, meta)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        build_app(),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", 7860)),
    )


if __name__ == "__main__":
    main()
