"""Publish corpus builds to a versioned Hugging Face Dataset.

Flow (driven by the GitHub workflows):
1. `fetch-manifest`: download the live `manifest.json` (from the dataset's `main`) to diff against.
2. `stage`: upload a new build to a dated branch, e.g. `update-2026-11-01`. Nothing user-facing
   changes yet.
3. `promote`: after the weekly PR is merged, copy that branch's files onto `main`.

The token comes from the HF_TOKEN environment variable (a GitHub Actions secret Ray sets).
The dataset itself must already exist: this never creates repos.

Usage:
    uv run irminsul-publish fetch-manifest --repo MukulRay/irminsul-corpus --out prev/
    uv run irminsul-publish stage --repo MukulRay/irminsul-corpus --build data/build \
        --branch update-2026-11-01
    uv run irminsul-publish promote --repo MukulRay/irminsul-corpus --branch update-2026-11-01
"""

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

PUBLISH_FILES = (
    "manifest.json",
    "docs.jsonl",
    "characters.jsonl",
    "weapons.jsonl",
    "artifact_sets.jsonl",
    "videos.jsonl",
    "planner.json",
    "CHANGELOG.md",
)
CARD = """---
license: other
license_name: mixed
pretty_name: Irminsul Genshin Impact corpus
---
# Irminsul corpus

Versioned, leak-gated Genshin Impact knowledge for the Irminsul assistant
(https://github.com/MukulRay1603/Irminsul).

- `tier=official`: in-game text (Yatta API) and HoYoverse's HoYoWiki. Genshin Impact
  content belongs to HoYoverse; this is an unofficial fan project.
- `tier=kqm`: derived from the KQM Theorycrafting Library, CC BY-NC-SA 4.0
  (https://github.com/KQM-git/TCL). Non-commercial, share-alike.

Only released or officially announced content is included. See `manifest.json` for
counts, source versions and every record the leak gate dropped.
"""


def _api():
    from huggingface_hub import HfApi

    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit("HF_TOKEN is not set; skipping Hugging Face publishing.")
    return HfApi(token=token)


def fetch_manifest(repo: str, out: Path) -> bool:
    """Download the live manifest; False if the dataset has none yet."""
    from huggingface_hub.errors import EntryNotFoundError, RepositoryNotFoundError

    api = _api()
    out.mkdir(parents=True, exist_ok=True)
    try:
        api.hf_hub_download(repo, "manifest.json", repo_type="dataset", local_dir=out)
        return True
    except (EntryNotFoundError, RepositoryNotFoundError):
        return False


def stage(repo: str, build: Path, branch: str, index: Path | None = None) -> None:
    api = _api()
    api.create_branch(repo, branch=branch, repo_type="dataset", exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for name in PUBLISH_FILES:
            if (build / name).exists():
                (folder / name).write_bytes((build / name).read_bytes())
        if index is not None and (index / "meta.json").exists():
            # The search index ships with the data so the app never re-embeds on boot.
            shutil.copytree(index, folder / "index")
        (folder / "README.md").write_text(CARD, encoding="utf-8")
        api.upload_folder(
            folder_path=folder,
            repo_id=repo,
            repo_type="dataset",
            revision=branch,
            commit_message=f"Stage corpus build {branch}",
        )


def promote(repo: str, branch: str) -> None:
    api = _api()
    with tempfile.TemporaryDirectory() as tmp:
        local = api.snapshot_download(repo, repo_type="dataset", revision=branch, local_dir=tmp)
        api.upload_folder(
            folder_path=local,
            repo_id=repo,
            repo_type="dataset",
            revision="main",
            commit_message=f"Publish corpus build {branch}",
            ignore_patterns=[".cache/*", ".gitattributes"],
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch-manifest")
    f.add_argument("--repo", required=True)
    f.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("stage")
    s.add_argument("--repo", required=True)
    s.add_argument("--build", type=Path, required=True)
    s.add_argument("--branch", required=True)
    s.add_argument("--index", type=Path, default=None, help="also upload this index folder")
    p = sub.add_parser("promote")
    p.add_argument("--repo", required=True)
    p.add_argument("--branch", required=True)
    args = parser.parse_args()
    if args.cmd == "fetch-manifest":
        print("found" if fetch_manifest(args.repo, args.out) else "no previous manifest")
    elif args.cmd == "stage":
        stage(args.repo, args.build, args.branch, args.index)
    else:
        promote(args.repo, args.branch)


if __name__ == "__main__":
    main()
