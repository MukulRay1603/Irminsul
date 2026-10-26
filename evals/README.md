# Golden eval set

Questions with checkable expectations, used to score retrieval and answers on every change.

| File | What | How it's made |
|---|---|---|
| `golden_manual.jsonl` | mechanics, builds, gacha, beginner facts, upcoming characters, and safety probes (leaks, off-topic, prompt injection) | hand-written; every factual expectation is sourced from official game data or the team's fact-checked notes |
| `golden_generated.jsonl` | exact stats, passives, constellations and set bonuses | generated from official game data (seeded, deterministic per corpus build) |

Each item (`src/irminsul/evals.py`) has:
- `expect`: `answer`, `partial` (officially announced: only the official part, and say the rest isn't official) or `refuse`
- `must_include`: groups of alternatives. Every group must match.
- `must_not_include`: text that must never appear
- `gold_doc_ids`: the docs retrieval should return, used for recall@k

**Rule:** a gold doc must literally contain each expected value. This was checked against the Oct 26 corpus build for all 107 items.

v0 (Oct 26 2026): 107 items. 73 generated from official data, 34 hand-written. Real viewer questions (via Recon) are next.
