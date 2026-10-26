# Retrieval benchmark: Oct 26 2026

**Corpus:**
- 2,854 docs: 1,397 official (Yatta game data + HoYoWiki), 1,429 KQM TCL sections, 28 team-verified note sections
- 3,361 chunks (≤300 words, 40-word overlap)

**Questions:** the 96 answerable items of the golden eval set (`evals/`, v0). Refusal probes have no gold docs.

**Hardware:** desktop CPU, no GPU (ONNX Runtime through fastembed).

**Metric:** doc level, so any chunk of a gold doc counts. hit@k = share of questions with a gold doc in the top k. MRR = mean 1/rank of the first gold doc.

## v0 vs v1 (same corpus, same questions)
| Config | hit@3 | MRR@3 | hit@8 | MRR@8 | p50 latency |
|---|---|---|---|---|---|
| **v0-style:** all-MiniLM-L6-v2, dense only | 0.490 | 0.405 | 0.677 | 0.441 | ~5 ms |
| v1 hybrid: BM25 + bge-small-en-v1.5, RRF | 0.792 | 0.653 | 0.896 | 0.676 | ~6 ms |
| **v1 hybrid + re-rank** (ms-marco-MiniLM-L-6, 20 candidates, 80-word window) | **0.875** | **0.812** | **0.979** | **0.834** | ~300 ms |

## Ablation (k = 8)
| Mode | hit@8 | MRR | p50 | Exact stats | Weapon / set passives | Mechanics |
|---|---|---|---|---|---|---|
| BM25 only | 0.844 | 0.599 | 0.2 ms | 0.755 | 0.897 | 1.0 |
| Dense only (bge-small) | 0.854 | 0.565 | 5.4 ms | 0.796 | 0.931 | 0.667 |
| Hybrid (RRF) | 0.875–0.896 | 0.674 | 5.6 ms | 0.796–0.816 | 0.966 | 0.833 |
| Hybrid + re-rank, 40 candidates, full chunks | 0.979 | 0.845 | 2,339 ms | 0.959 | 1.0 | 1.0 |
| **Hybrid + re-rank, 20 candidates, 80 words** | **0.979** | **0.834** | **300 ms** | **0.98** | 1.0 | 1.0 |

## Re-ranker tuning (hybrid + re-rank, k = 8)
| Re-ranker | Candidates | Words | hit@8 | MRR | p50 |
|---|---|---|---|---|---|
| ms-marco-MiniLM-L-6-v2 | 12 | full | 0.958 | 0.849 | 659 ms |
| ms-marco-MiniLM-L-6-v2 | 20 | full | 0.979 | 0.846 | 1,155 ms |
| jina-reranker-v1-tiny-en | 12 | full | 0.948 | 0.825 | 604 ms |
| jina-reranker-v1-tiny-en | 20 | full | 0.958 | 0.817 | 1,090 ms |
| ms-marco-MiniLM-L-6-v2 | 20 | 120 | 0.969 | 0.838 | 475 ms |
| **ms-marco-MiniLM-L-6-v2** | **20** | **80** | **0.979** | **0.834** | **300 ms** |
| ms-marco-MiniLM-L-6-v2 | 30 | 80 | 0.958 | 0.825 | 489 ms |

## Takeaways
- **Keyword search and embeddings fail on different questions,** so fusing them (RRF) beats either alone.
- **The re-ranker is the biggest single gain** (+0.08–0.10 hit@8, +0.16 MRR). Most of its cost is passage length, and trimming to 80 words kept quality at 1/8 the latency.
- **Weakest category: exact stats.** Many characters' overview docs look alike to an embedding model. Routing stat questions to the structured entity store (P2 next) fixes that without an LLM.

Reproduce:
```bash
uv run irminsul-index build --docs data/corpus-all.jsonl --out data/index
uv run irminsul-index eval --index data/index --k 8
```
