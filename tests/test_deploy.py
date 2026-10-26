"""The Space README the deploy writes must pass Hugging Face's metadata rules."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "deploy_space.py"


def load_readme() -> str:
    spec = importlib.util.spec_from_file_location("deploy_space", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SPACE_README


def test_space_front_matter_follows_hf_rules():
    readme = load_readme()
    front = readme.split("---")[1]
    fields = dict(line.split(": ", 1) for line in front.strip().splitlines())
    assert fields["sdk"] == "docker" and fields["app_port"] == "7860"
    assert len(fields["short_description"]) <= 60  # HF rejects longer descriptions
