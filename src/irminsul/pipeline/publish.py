"""Publish corpus builds to a versioned Hugging Face Dataset.

Flow (driven by the GitHub workflows):
1. `fetch-manifest`: download the live `manifest.json` (from the dataset's `main`) to diff against,
   with the live `history.json` and records the change history needs.
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
import contextlib
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
    "history.json",
    "CHANGELOG.md",
)
# Downloaded with the live manifest: the history to append to, and the records and videos
# the change history compares field by field (see history.py). All optional.
PREVIOUS_FILES = (
    "history.json",
    "characters.jsonl",
    "weapons.jsonl",
    "artifact_sets.jsonl",
    "videos.jsonl",
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
    except (EntryNotFoundError, RepositoryNotFoundError):
        return False
    for name in PREVIOUS_FILES:
        # Missing is fine, e.g. no history.json before the first build that writes one
        with contextlib.suppress(EntryNotFoundError):
            api.hf_hub_download(repo, name, repo_type="dataset", local_dir=out)
    return True


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


# Curated team files (facts and build recommendations) live only in the private dataset, under
# curated/, not in the public repo: the build fetches them, publishing never deletes them.
CURATED_FILES = ("team_facts.md", "team_builds.md")


def upload_curated(repo: str, folder: Path) -> list[str]:
    files = [name for name in CURATED_FILES if (folder / name).exists()]
    if not files:
        sys.exit(f"no curated files in {folder}")
    _api().upload_folder(
        folder_path=folder,
        path_in_repo="curated",
        repo_id=repo,
        repo_type="dataset",
        revision="main",
        allow_patterns=files,
        commit_message="Update curated team files: " + ", ".join(files),
    )
    return files


def fetch_curated(repo: str, out: Path) -> list[str]:
    """Download the curated files into `out` (config/ for the build). Fails if any is missing:
    a build without them would quietly publish without the team's facts and builds."""
    api = _api()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(
            api.snapshot_download(
                repo, repo_type="dataset", allow_patterns=["curated/*.md"], local_dir=tmp
            )
        )
        missing = [name for name in CURATED_FILES if not (local / "curated" / name).exists()]
        if missing:
            sys.exit(f"curated files missing from {repo}: {', '.join(missing)}")
        for name in CURATED_FILES:
            (out / name).write_bytes((local / "curated" / name).read_bytes())
    return list(CURATED_FILES)


def restart_space(space: str) -> None:
    """The Space loads the dataset at boot, so a restart is what makes a new build live."""
    _api().restart_space(space)


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
    r = sub.add_parser("restart-space")
    r.add_argument("--space", required=True)
    u = sub.add_parser("upload-curated")
    u.add_argument("--repo", required=True)
    u.add_argument("--dir", type=Path, required=True)
    c = sub.add_parser("fetch-curated")
    c.add_argument("--repo", required=True)
    c.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.cmd == "fetch-manifest":
        print("found" if fetch_manifest(args.repo, args.out) else "no previous manifest")
    elif args.cmd == "upload-curated":
        print("uploaded", ", ".join(upload_curated(args.repo, args.dir)))
    elif args.cmd == "fetch-curated":
        print("fetched", ", ".join(fetch_curated(args.repo, args.out)))
    elif args.cmd == "stage":
        stage(args.repo, args.build, args.branch, args.index)
    elif args.cmd == "restart-space":
        restart_space(args.space)
    else:
        promote(args.repo, args.branch)


if __name__ == "__main__":
    main()
