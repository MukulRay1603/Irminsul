# Retrieval benchmark: Oct 26 2026

**Corpus:**
- 2,854 docs: 1,397 official (game data + HoYoWiki), 1,429 KQM TCL sections, 28 team-verified note sections
- 3,361 searchable passages

**Questions:** the 96 answerable items of the golden eval set (`evals/`, v0). Refusal probes have no gold docs.

**Hardware:** desktop CPU, no GPU.

**Metric:** doc level, so any passage of a gold doc counts. hit@k = share of questions with a gold doc in the top k. MRR = mean 1/rank of the first gold doc.

## v0 vs v1 (same corpus, same questions)
| Config | hit@3 | MRR@3 | hit@8 | MRR@8 | p50 latency |
|---|---|---|---|---|---|
| **v0-style:** meaning-based search only | 0.490 | 0.405 | 0.677 | 0.441 | ~5 ms |
| v1 hybrid: keyword + meaning-based, fused | 0.792 | 0.653 | 0.896 | 0.676 | ~6 ms |
| **v1 hybrid + re-rank** | **0.875** | **0.812** | **0.979** | **0.834** | ~300 ms |

## Ablation (k = 8)
| Mode | hit@8 | MRR | Exact stats | Weapon / set passives | Mechanics |
|---|---|---|---|---|---|
| Keyword only | 0.844 | 0.599 | 0.755 | 0.897 | 1.0 |
| Meaning-based only | 0.854 | 0.565 | 0.796 | 0.931 | 0.667 |
| Hybrid | 0.875–0.896 | 0.674 | 0.796–0.816 | 0.966 | 0.833 |
| **Hybrid + re-rank** | **0.979** | **0.834** | **0.98** | 1.0 | 1.0 |

## Takeaways
- **Keyword search and meaning-based search fail on different questions,** so fusing them beats either alone.
- **The re-ranker is the biggest single gain** (+0.08–0.10 hit@8, +0.16 MRR). Tuning how much of each passage it reads kept that quality at about 1/8 of the latency.
- **Weakest category: exact stats.** Many characters' overview docs look alike to search. Routing stat questions to the structured game data instead fixes that without an AI.
