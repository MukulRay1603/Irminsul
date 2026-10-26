"""Public test results: run the offline evals (no LLM, no network), write web/static/results.json.

Usage:
    uv run irminsul-report --build data/build [--index data/index]   # regenerate
    uv run irminsul-report --check                                   # CI: verify the file

What it measures:
- the golden eval set through the answer engine with no model calls (engine/evaluate.py):
  stat accuracy, leak probes and other refusal probes
- retrieval hit@3 / hit@8 and MRR on the same set (retrieval/evaluate.py), when an index exists
- cost per answer: AI answers run on free tiers ($0); for reference, what they would cost at
  Groq's paid price for an answer of ~3.5K input and ~0.5K output tokens

--check needs no data: it validates the committed file's shape and recomputes everything that
comes from the repo itself (eval set counts, cost figures), so a changed eval set or price fails
CI until the file is regenerated.
"""

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from irminsul.evals import Category, Expect, load

OUT = Path(__file__).resolve().parents[2] / "web" / "static" / "results.json"
SCHEMA = 1
# Groq's paid on-demand price for the model the free tier runs (USD per 1M tokens).
PRICE = {"provider": "Groq", "input_per_m": 0.15, "output_per_m": 0.60}
TOKENS = {"input": 3500, "output": 500}  # a typical AI answer: 6 sources of ~180 words + prompt
REFUSAL_PROBES = (Category.INJECTION, Category.OFFTOPIC)
RETRIEVAL_CONFIG = "hybrid+rerank"  # what the app runs


def eval_set() -> dict:
    """Counts that come from the eval files alone."""
    items = load()
    by_cat = Counter(i.category.value for i in items)
    return {
        "items": len(items),
        "answerable": sum(1 for i in items if i.expect != Expect.REFUSE),
        "by_category": dict(sorted(by_cat.items())),
    }


def cost(ai_share: float | None) -> dict:
    per_ai = (
        TOKENS["input"] * PRICE["input_per_m"] + TOKENS["output"] * PRICE["output_per_m"]
    ) / 1e6
    return {
        "per_ai_answer_usd": 0.0,
        "note": "AI answers run on free API tiers; answers from game data use no AI at all.",
        "paid_reference": {
            **PRICE,
            "tokens_per_ai_answer": TOKENS,
            "per_ai_answer_usd": round(per_ai, 6),
            "per_1000_ai_answers_usd": round(per_ai * 1000, 3),
        },
        "ai_share_of_eval_set": ai_share,
        "per_answer_blended_usd": round(per_ai * ai_share, 6) if ai_share is not None else None,
    }


def _ratio(text: str | None) -> dict | None:
    if not text:
        return None
    passed, total = (int(x) for x in text.split("/"))
    return {"passed": passed, "total": total, "rate": round(passed / total, 3) if total else None}


def answers(build: Path) -> tuple[dict, str | None]:
    from irminsul.engine.engine import Engine
    from irminsul.engine.entities import EntityStore
    from irminsul.engine.evaluate import evaluate
    from irminsul.engine.guards import GuardConfig, version_from_manifest

    manifest = json.loads((build / "manifest.json").read_text(encoding="utf-8"))
    live = version_from_manifest(manifest.get("sources", {}).get("yatta", {}).get("game_version"))
    cfg = GuardConfig(live, (live[0], live[1] + 1)) if live else GuardConfig()
    report = evaluate(Engine(EntityStore.load(build), None, None, cfg))
    cats = report["by_category"]
    refusals = [_ratio(cats.get(c.value)) for c in REFUSAL_PROBES]
    refusals = [r for r in refusals if r]
    return {
        "scored": report["scored"],
        "passed": report["scored"] - len(report["failures"]),
        "needs_llm": report["needs_llm"],
        "pass_rate": report["pass_rate"],
        "stat_accuracy": _ratio(cats.get(Category.STAT.value)),
        "passive_accuracy": _ratio(cats.get(Category.PASSIVE.value)),
        "leak_probes": _ratio(cats.get(Category.LEAK_PROBE.value)),
        "refusal_probes": {
            "passed": sum(r["passed"] for r in refusals),
            "total": sum(r["total"] for r in refusals),
        },
        "by_category": {c: _ratio(v) for c, v in cats.items()},
        "failures": [{"id": f["id"], "problems": f["problems"]} for f in report["failures"]],
    }, f"{live[0]}.{live[1]}" if live else None


def retrieval(index_dir: Path) -> dict:
    from irminsul.retrieval.evaluate import CONFIGS, score
    from irminsul.retrieval.index import HybridIndex

    index = HybridIndex.load(index_dir)
    configs = {RETRIEVAL_CONFIG: CONFIGS[RETRIEVAL_CONFIG]}
    at3, at8 = (score(index, k, configs) for k in (3, 8))
    r3, r8 = at3["configs"][RETRIEVAL_CONFIG], at8["configs"][RETRIEVAL_CONFIG]
    return {
        "config": RETRIEVAL_CONFIG,
        "embed_model": index.embed_model,
        "questions": at8["questions"],
        "chunks": len(index.chunks),
        "hit_at_3": r3["hit@3"],
        "hit_at_8": r8["hit@8"],
        "mrr_at_3": r3["mrr"],
        "mrr_at_8": r8["mrr"],
        "p50_ms": r8["p50_ms"],
    }


def generate(build: Path, index_dir: Path | None) -> dict:
    ans, version = answers(build)
    items = eval_set()
    ai_share = round(ans["needs_llm"] / items["items"], 3) if items["items"] else None
    return {
        "schema": SCHEMA,
        "generated": datetime.now(UTC).date().isoformat(),
        "game_version": version,
        "eval_set": items,
        "answers": ans,
        "retrieval": retrieval(index_dir)
        if index_dir and (index_dir / "meta.json").exists()
        else None,
        "cost": cost(ai_share),
    }


def problems(data: dict) -> list[str]:
    """Why a results file is malformed or stale; empty when it is fine."""
    out = []
    want = {
        "schema": int,
        "generated": str,
        "game_version": (str, type(None)),
        "eval_set": dict,
        "answers": dict,
        "retrieval": (dict, type(None)),
        "cost": dict,
    }
    for key, kind in want.items():
        if not isinstance(data.get(key), kind):
            out.append(f"{key}: missing or wrong type")
    if out:
        return out
    if data["schema"] != SCHEMA:
        out.append(f"schema {data['schema']} != {SCHEMA}")
    if data["eval_set"] != eval_set():
        out.append("eval set changed since the results were generated")
    a = data["answers"]
    for key in ("scored", "passed", "needs_llm"):
        if not isinstance(a.get(key), int):
            out.append(f"answers.{key}: missing")
    for key in ("stat_accuracy", "leak_probes", "refusal_probes"):
        if not (isinstance(a.get(key), dict) and {"passed", "total"} <= a[key].keys()):
            out.append(f"answers.{key}: missing")
    if not out and a["scored"] + a["needs_llm"] != data["eval_set"]["items"]:
        out.append("answers don't add up to the eval set")
    r = data["retrieval"]
    if r is not None:
        for key in ("hit_at_3", "hit_at_8", "mrr_at_3", "mrr_at_8"):
            if not (isinstance(r.get(key), int | float) and 0 <= r[key] <= 1):
                out.append(f"retrieval.{key}: missing or out of range")
    share = data["cost"].get("ai_share_of_eval_set")
    if data["cost"] != cost(share):
        out.append("cost figures are stale (price or token assumptions changed)")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--build", type=Path, default=Path("data/build"))
    parser.add_argument("--index", type=Path, default=Path("data/index"))
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--check", action="store_true", help="verify --out instead of writing it")
    args = parser.parse_args()

    if args.check:
        found = problems(json.loads(args.out.read_text(encoding="utf-8")))
        if found:
            sys.exit(
                "results.json needs regenerating (uv run irminsul-report):\n- " + "\n- ".join(found)
            )
        print(f"{args.out} is up to date")
        return
    data = generate(args.build, args.index)
    if found := problems(data):
        sys.exit("generated results are inconsistent:\n- " + "\n- ".join(found))
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: data[k] for k in ("game_version", "eval_set", "retrieval")}, indent=2))


if __name__ == "__main__":
    main()
