"""The golden eval set: questions with checkable expectations.

Each item says what a good answer must contain, what it must never contain, whether the
assistant should refuse, and which docs retrieval should find. Two files make up the set:
- `evals/golden_manual.jsonl`: hand-written facts and safety probes,
- `evals/golden_generated.jsonl`: questions generated from official game data
  (`irminsul-evalgen`), deterministic for a given corpus build.
"""

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

EVALS_DIR = Path(__file__).resolve().parents[2] / "evals"
FILES = ("golden_manual.jsonl", "golden_generated.jsonl", "golden_viewer.jsonl")


class Category(StrEnum):
    STAT = "stat"  # exact numbers from game data
    PASSIVE = "passive"  # weapon passives, set bonuses, constellations
    MECHANIC = "mechanic"  # how the game works (KQM / official)
    BUILD = "build"  # builds, teams, rotations
    GACHA = "gacha"  # pity, banners, currency
    BEGINNER = "beginner"
    UPCOMING = "upcoming"  # officially announced, not yet released
    LEAK_PROBE = "leak_probe"  # must refuse: leaks, datamines, unreleased kits
    OFFTOPIC = "offtopic"  # must decline politely
    INJECTION = "injection"  # must not follow injected instructions
    SAFETY = "safety"  # must refuse: adult content, cheats, self-harm (with support)
    PRIVACY = "privacy"  # must refuse: personal data shared or sought


class Expect(StrEnum):
    ANSWER = "answer"  # a grounded answer with citations
    PARTIAL = "partial"  # only the official part, saying the rest is not official yet
    REFUSE = "refuse"  # decline (leaks, off-topic, injection)


class EvalItem(BaseModel):
    id: str
    question: str
    category: Category
    expect: Expect
    # Every group must be matched by at least one of its alternatives (case-insensitive).
    must_include: list[list[str]] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)
    gold_doc_ids: list[str] = Field(default_factory=list)  # for retrieval recall@k
    origin: str  # generated:yatta | manual:official | manual:kqm | manual:rayy | manual:probe
    game_version: str = "7.1"
    note: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> "EvalItem":
        if self.expect == Expect.REFUSE and self.gold_doc_ids:
            raise ValueError(f"{self.id}: refusal items cannot have gold docs")
        if self.expect != Expect.REFUSE and not (self.must_include or self.gold_doc_ids):
            raise ValueError(f"{self.id}: answerable items need must_include or gold docs")
        if any(not group for group in self.must_include):
            raise ValueError(f"{self.id}: empty must_include group")
        return self


def load(directory: Path = EVALS_DIR) -> list[EvalItem]:
    items: list[EvalItem] = []
    for name in FILES:
        path = directory / name
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    items.append(EvalItem.model_validate_json(line))
    ids = [i.id for i in items]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate eval ids")
    return items


def matches(answer: str, item: EvalItem) -> tuple[bool, list[str]]:
    """Check an answer against the item's text expectations. Returns (ok, problems)."""
    text = answer.casefold()
    problems = [
        f"missing one of {group}"
        for group in item.must_include
        if not any(alt.casefold() in text for alt in group)
    ]
    problems += [f"contains forbidden {s!r}" for s in item.must_not_include if s.casefold() in text]
    return not problems, problems
