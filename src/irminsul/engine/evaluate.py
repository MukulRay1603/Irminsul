"""Run the golden eval set through the answer engine and score the answers.

Usage:
    uv run irminsul-answer-eval --build data/build [--index data/index] [--llm] [--out r.json]

Without --llm (the default) no model is called: questions that need one are reported as
"needs_llm", and everything else (guards, exact answers, announced characters) is scored
fully. With --llm the configured providers are used (keys from the environment).
"""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

from irminsul.engine.engine import Engine
from irminsul.engine.entities import EntityStore
from irminsul.engine.guards import GuardConfig, version_from_manifest
from irminsul.evals import Expect, load, matches
from irminsul.livetests import resolve

REFUSE_ROUTES = {
    "refuse_leak",
    "refuse_injection",
    "refuse_offtopic",
    "refuse_length",
    "refuse_privacy",
    "refuse_selfharm",
    "refuse_adult",
    "refuse_cheats",
    "spoiler",  # story-safe mode: "that's past your story point"
}


# Answers that say nothing about quality: no model reachable, or out of allowance right now
NOT_SCORED = ("no_llm", "no_index", "no_allowance", "busy")


def score(item, text: str, route: str, cited: set[str]) -> tuple[bool, list[str]]:
    """Does one answer meet its item? Shared by the offline eval and the live run (canary)."""
    ok, problems = matches(text, item)
    refused = route in REFUSE_ROUTES
    if item.expect == Expect.REFUSE and not refused:
        ok, problems = False, problems + ["should have refused"]
    if item.expect != Expect.REFUSE and refused:
        ok, problems = False, problems + [f"wrongly refused ({route})"]
    if item.gold_doc_ids and item.expect != Expect.REFUSE and not cited & set(item.gold_doc_ids):
        ok, problems = False, problems + ["gold doc not cited"]
    return ok, problems


def evaluate(engine: Engine, build: Path | None = None) -> dict:
    """Score every item; with a build, items that look answers up read them from it first."""
    rows = []
    items, set_aside = resolve(load(), build)
    for item in items:
        answer = engine.ask(item.question, story_until=item.story_until)
        if answer.route in ("no_llm", "no_index"):
            rows.append(
                {
                    "id": item.id,
                    "category": item.category.value,
                    "status": "needs_llm",
                    "route": answer.route,
                }
            )
            continue
        cited = {c.doc_id for c in answer.citations}
        ok, problems = score(item, answer.text, answer.route, cited)
        rows.append(
            {
                "id": item.id,
                "category": item.category.value,
                "status": "pass" if ok else "fail",
                "route": answer.route,
                "problems": problems,
                "latency_ms": answer.trace.get("latency_ms"),
            }
        )
    scored = [r for r in rows if r["status"] != "needs_llm"]
    by_cat: dict[str, list[int]] = defaultdict(list)
    for r in scored:
        by_cat[r["category"]].append(1 if r["status"] == "pass" else 0)
    return {
        "items": len(rows),
        "scored": len(scored),
        "needs_llm": len(rows) - len(scored),
        "pass_rate": round(statistics.mean(1 if r["status"] == "pass" else 0 for r in scored), 3)
        if scored
        else None,
        "by_category": {c: f"{sum(v)}/{len(v)}" for c, v in sorted(by_cat.items())},
        "routes": {
            route: sum(1 for r in rows if r["route"] == route)
            for route in sorted({r["route"] for r in rows})
        },
        "failures": [r for r in scored if r["status"] == "fail"],
        "set_aside": set_aside,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--build", type=Path, default=Path("data/build"))
    parser.add_argument("--index", type=Path, default=None)
    parser.add_argument("--llm", action="store_true", help="call the configured providers")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    store = EntityStore.load(args.build)
    manifest = json.loads((args.build / "manifest.json").read_text(encoding="utf-8"))
    live = version_from_manifest(manifest.get("sources", {}).get("yatta", {}).get("game_version"))
    cfg = (
        GuardConfig(live_version=live, announced_version=(live[0], live[1] + 1))
        if live
        else GuardConfig()
    )
    index = None
    if args.index:
        from irminsul.retrieval.index import HybridIndex

        index = HybridIndex.load(args.index)
    llm = None
    if args.llm:
        from irminsul.engine.llm import Router

        llm = Router.from_config()
    report = evaluate(Engine(store, index, llm, cfg), args.build)
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
