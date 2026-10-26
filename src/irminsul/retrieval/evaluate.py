"""Build an index from corpus docs and score retrieval on the golden eval set.

Usage:
    uv run irminsul-index build --docs data/build/docs.jsonl [more.jsonl ...] --out data/index
    uv run irminsul-index eval --index data/index

Metrics (doc level: any chunk of a gold doc counts as finding it):
- hit@k: share of questions with at least one gold doc in the top k
- recall@k: share of each question's gold docs found in the top k, averaged
- MRR: mean of 1 / rank of the first gold doc (0 if not in the top k)
"""

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from irminsul.evals import Expect, load
from irminsul.retrieval.chunking import chunk_docs
from irminsul.retrieval.index import EMBED_MODEL, HybridIndex, timed_search
from irminsul.schema import Doc

CONFIGS = {
    "bm25": {"mode": "bm25"},
    "dense": {"mode": "dense"},
    "hybrid": {"mode": "hybrid"},
    "hybrid+rerank": {"mode": "hybrid", "rerank": True},
}


def load_docs(paths: list[Path]) -> list[Doc]:
    docs: dict[str, Doc] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line:
                doc = Doc.model_validate_json(line)
                docs.setdefault(doc.doc_id, doc)  # first file wins on duplicates
    return list(docs.values())


def score(index: HybridIndex, k: int = 8, configs: dict | None = None) -> dict:
    # Skip questions whose gold docs are not in this index (e.g. CI builds have no local
    # team notes): those measure corpus coverage, not retrieval.
    indexed = {c.doc_id for c in index.chunks}
    answerable = [i for i in load() if i.expect != Expect.REFUSE and i.gold_doc_ids]
    items = [i for i in answerable if set(i.gold_doc_ids) <= indexed]
    report: dict = {
        "questions": len(items),
        "skipped_missing_gold": sorted(i.id for i in answerable if i not in items),
        "k": k,
        "configs": {},
    }
    if not items:
        return report
    for name, cfg in (configs or CONFIGS).items():
        hits_at, recalls, rrs, latencies = [], [], [], []
        by_cat: dict[str, list[int]] = defaultdict(list)
        for item in items:
            hits, ms = timed_search(index, item.question, k=k, **cfg)
            latencies.append(ms)
            ranked_docs = list(dict.fromkeys(h.chunk.doc_id for h in hits))
            gold = set(item.gold_doc_ids)
            found = gold & set(ranked_docs)
            first = next((r for r, d in enumerate(ranked_docs, 1) if d in gold), None)
            hits_at.append(1 if found else 0)
            recalls.append(len(found) / len(gold))
            rrs.append(1 / first if first else 0.0)
            by_cat[item.category.value].append(1 if found else 0)
        latencies.sort()
        report["configs"][name] = {
            f"hit@{k}": round(statistics.mean(hits_at), 3),
            f"recall@{k}": round(statistics.mean(recalls), 3),
            "mrr": round(statistics.mean(rrs), 3),
            "p50_ms": round(latencies[len(latencies) // 2], 1),
            "p95_ms": round(latencies[int(len(latencies) * 0.95) - 1], 1),
            "hit_by_category": {c: round(statistics.mean(v), 3) for c, v in sorted(by_cat.items())},
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--docs", type=Path, nargs="+", required=True)
    b.add_argument("--out", type=Path, default=Path("data/index"))
    b.add_argument("--embed-model", default=EMBED_MODEL)
    b.add_argument("--max-words", type=int, default=300)
    e = sub.add_parser("eval")
    e.add_argument("--index", type=Path, default=Path("data/index"))
    e.add_argument("--k", type=int, default=8)
    e.add_argument("--configs", nargs="*", default=list(CONFIGS))
    e.add_argument("--out", type=Path, default=None, help="write the JSON report here")
    e.add_argument(
        "--min-hit",
        type=float,
        default=None,
        help="exit 1 if any config's hit@k is below this (quality gate)",
    )
    args = parser.parse_args()

    if args.cmd == "build":
        chunks = chunk_docs(load_docs(args.docs), max_words=args.max_words)
        HybridIndex.build(chunks, args.embed_model).save(args.out)
        print(f"indexed {len(chunks)} chunks with {args.embed_model} -> {args.out}")
    else:
        index = HybridIndex.load(args.index)
        report = score(index, args.k, {c: CONFIGS[c] for c in args.configs})
        report["embed_model"] = index.embed_model
        text = json.dumps(report, indent=2)
        if args.out:
            args.out.write_text(text, encoding="utf-8")
        print(text)
        if args.min_hit is not None:
            low = {
                n: c[f"hit@{args.k}"]
                for n, c in report["configs"].items()
                if c[f"hit@{args.k}"] < args.min_hit
            }
            if low:
                sys.exit(f"retrieval quality gate failed: {low} < {args.min_hit}")


if __name__ == "__main__":
    main()
