"""Deploy the app to the Hugging Face Space: upload exactly what the Docker image needs.

Run by .github/workflows/deploy-space.yml (manual trigger) with HF_TOKEN from GitHub secrets.
The Space gets its own README with the front matter Spaces require; the GitHub README is left
alone. Files from earlier deploys (e.g. v0) are removed from the Space's working tree; the
Space repo's git history still keeps them.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
SHIP = ["Dockerfile", ".dockerignore", "pyproject.toml", "uv.lock", "LICENSE", "src", "config", "web"]
SPACE_README = """---
title: Irminsul
emoji: 🌳
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: Genshin answers from official game data, with sources. No leaks.
---

# Irminsul

An unofficial, free Genshin Impact assistant. It answers from official game data, shows its
sources, and never discusses leaks. Source and design: https://github.com/MukulRay1603/Irminsul

Not affiliated with or endorsed by HoYoverse. Genshin Impact content belongs to HoYoverse.
"""


def main() -> int:
    space = os.environ.get("SPACE_ID", "MukulRay/Irminsul")
    token = os.environ.get("HF_TOKEN")
    if not token:
        print("HF_TOKEN is not set: add it as a GitHub Actions secret first.", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        for name in SHIP:
            src = ROOT / name
            if src.is_dir():
                shutil.copytree(src, out / name, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(src, out / name)
        (out / "README.md").write_text(SPACE_README, encoding="utf-8")
        commit = os.environ.get("GITHUB_SHA", "local")[:7]
        HfApi(token=token).upload_folder(
            repo_id=space,
            repo_type="space",
            folder_path=out,
            commit_message=f"Deploy Irminsul v1 ({commit})",
            delete_patterns=["*"],  # replace the old tree; history keeps earlier versions
        )
    print(f"Uploaded to https://huggingface.co/spaces/{space}: the Space rebuilds now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
