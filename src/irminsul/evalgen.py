"""Generate eval questions from official game data in a corpus build.

Usage:
    uv run irminsul-evalgen --build data/build --out evals/golden_generated.jsonl

Sampling is seeded, so the same build always yields the same questions. Answers come
straight from the entity records, so these items measure exact-fact accuracy.
"""

import argparse
import json
import random
import re
from pathlib import Path

from irminsul.evals import Category, EvalItem, Expect

_PERCENT = re.compile(r"\d+(?:\.\d+)?%")


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


STAT_ALIASES = {
    "ATK%": ["ATK", "Attack"],
    "HP%": ["HP"],
    "DEF%": ["DEF", "Defense"],
    "CRIT Rate": ["CRIT Rate"],
    "CRIT DMG": ["CRIT DMG", "CRIT Damage"],
    "Elemental Mastery": ["Elemental Mastery", "EM"],
}


def _stat(name: str) -> list[str]:
    return STAT_ALIASES.get(name, [name])


def _pct(value: float) -> list[str]:
    """Accept 32.0% written as '32%' or '32.0%'."""
    one = f"{value * 100:.1f}%"
    return [one, one.replace(".0%", "%")] if one.endswith(".0%") else [one]


def character_items(chars: list[dict], rng: random.Random, n: int) -> list[EvalItem]:
    pool = [
        c
        for c in chars
        if c["release"]["status"] == "released"
        and c.get("base_stats")
        and not c["id"].startswith("character/traveler")
    ]
    items = []
    for c in rng.sample(pool, min(n, len(pool))):
        s, slug = c["base_stats"], c["id"].split("/", 1)[1]
        items.append(
            EvalItem(
                id=f"gen-char-atk-{slug}",
                question=f"What is {c['name']}'s base ATK at level 90?",
                category=Category.STAT,
                expect=Expect.ANSWER,
                must_include=[[f"{s['atk']:.0f}"]],
                gold_doc_ids=[f"{c['id']}#overview"],
                origin="generated:yatta",
            )
        )
        if s.get("bonus_stat") and s.get("bonus_value") is not None:
            value = f"{s['bonus_value']:.0f}" if s["bonus_stat"] == "Elemental Mastery" else None
            items.append(
                EvalItem(
                    id=f"gen-char-ascstat-{slug}",
                    question=f"What stat does {c['name']} gain from ascension, and how much at 90?",
                    category=Category.STAT,
                    expect=Expect.ANSWER,
                    must_include=[
                        _stat(s["bonus_stat"]),
                        [value] if value else _pct(s["bonus_value"]),
                    ],
                    gold_doc_ids=[f"{c['id']}#overview"],
                    origin="generated:yatta",
                )
            )
        items.append(
            EvalItem(
                id=f"gen-char-kind-{slug}",
                question=f"What element and weapon type does {c['name']} use?",
                category=Category.STAT,
                expect=Expect.ANSWER,
                must_include=[[c["element"]], [c["weapon_type"]]],
                gold_doc_ids=[f"{c['id']}#overview"],
                origin="generated:yatta",
            )
        )
    return items


def constellation_items(chars: list[dict], rng: random.Random, n: int) -> list[EvalItem]:
    pool = [
        c
        for c in chars
        if c["release"]["status"] == "released"
        and c["constellations"]
        and not c["id"].startswith("character/traveler")
    ]
    items = []
    for c in rng.sample(pool, min(n, len(pool))):
        con = rng.choice(c["constellations"])
        slug = c["id"].split("/", 1)[1]
        items.append(
            EvalItem(
                id=f"gen-con-{slug}-c{con['level']}",
                question=f"What is the name of {c['name']}'s C{con['level']}?",
                category=Category.PASSIVE,
                expect=Expect.ANSWER,
                must_include=[[con["name"]]],
                gold_doc_ids=[f"{c['id']}#constellations"],
                origin="generated:yatta",
            )
        )
    return items


def weapon_items(weapons: list[dict], rng: random.Random, n: int) -> list[EvalItem]:
    pool = [
        w for w in weapons if w["rarity"] >= 4 and w.get("base_atk") and w["passive_by_refinement"]
    ]
    items = []
    for w in rng.sample(pool, min(n, len(pool))):
        slug = w["id"].split("/", 1)[1]
        stat_groups = [[f"{w['base_atk']:.0f}"]]
        if w.get("secondary_stat") and w.get("secondary_value") is not None:
            stat_groups.append(_stat(w["secondary_stat"]))
        items.append(
            EvalItem(
                id=f"gen-weapon-stats-{slug}",
                question=f"What are {w['name']}'s base ATK and secondary stat at max level?",
                category=Category.STAT,
                expect=Expect.ANSWER,
                must_include=stat_groups,
                gold_doc_ids=[f"{w['id']}#main"],
                origin="generated:yatta",
            )
        )
        if numbers := _PERCENT.findall(w["passive_by_refinement"][0]):
            items.append(
                EvalItem(
                    id=f"gen-weapon-r1-{slug}",
                    question=f"What does {w['name']}'s passive do at R1?",
                    category=Category.PASSIVE,
                    expect=Expect.ANSWER,
                    must_include=[[numbers[0]]],
                    gold_doc_ids=[f"{w['id']}#main"],
                    origin="generated:yatta",
                )
            )
    return items


def artifact_items(sets: list[dict], rng: random.Random, n: int) -> list[EvalItem]:
    pool = [a for a in sets if "4" in a["bonuses"] and _PERCENT.search(a["bonuses"]["4"])]
    items = []
    for a in rng.sample(pool, min(n, len(pool))):
        slug = a["id"].split("/", 1)[1]
        items.append(
            EvalItem(
                id=f"gen-artifact-4pc-{slug}",
                question=f"What is the 4-piece bonus of {a['name']}?",
                category=Category.PASSIVE,
                expect=Expect.ANSWER,
                must_include=[[_PERCENT.search(a["bonuses"]["4"]).group()]],
                gold_doc_ids=[f"{a['id']}#main"],
                origin="generated:yatta",
            )
        )
    return items


def generate(build: Path, seed: int = 7) -> list[EvalItem]:
    rng = random.Random(seed)
    chars = _read(build / "characters.jsonl")
    return (
        character_items(chars, rng, 12)
        + constellation_items(chars, rng, 8)
        + weapon_items(_read(build / "weapons.jsonl"), rng, 12)
        + artifact_items(_read(build / "artifact_sets.jsonl"), rng, 8)
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--build", type=Path, default=Path("data/build"))
    parser.add_argument("--out", type=Path, default=Path("evals/golden_generated.jsonl"))
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    items = generate(args.build, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(i.model_dump_json() + "\n" for i in items), encoding="utf-8")
    print(f"wrote {len(items)} items to {args.out}")


if __name__ == "__main__":
    main()
