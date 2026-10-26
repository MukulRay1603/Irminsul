import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
FETCHED_AT = datetime(2026, 10, 26, tzinfo=UTC)


def load_yatta(name: str) -> dict:
    return json.loads((FIXTURES / "yatta" / f"{name}.json").read_text(encoding="utf-8"))["data"]


@pytest.fixture
def avatar_curve() -> dict:
    return load_yatta("avatarCurve")


@pytest.fixture
def weapon_curve() -> dict:
    return load_yatta("weaponCurve")
