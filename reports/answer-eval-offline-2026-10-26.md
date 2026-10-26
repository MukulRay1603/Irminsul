# Answer eval (offline, no LLM): Oct 26 2026

Engine run over the 107-item golden set with **no model calls**. Corpus: the full combined build (Yatta + HoYoWiki + KQM).

| Route | Items | Result |
|---|---|---|
| Exact answer from game data (stats, ascension stats, constellations, weapon passives, set bonuses) | 77 | **77/77 pass** |
| Announced character, overview only (Mitya, Valeriy) | 3 | **3/3 pass** |
| Leak / future-version refusal | 5 | **5/5 refused** |
| Prompt-injection refusal | 3 | **3/3 refused** |
| Off-topic refusal (incl. another HoYoverse game) | 3 | **3/3 refused** |
| Needs retrieval + LLM (mechanics, builds, gacha, beginner) | 16 | scored once LLM keys exist |

**91/91 scored items pass. 0 LLM tokens spent.** Exact answers take ~0.1 ms. A guard refusal takes ~0 ms.

## Pass criteria
- every `must_include` group is present
- no `must_not_include` text appears
- the expected route was taken (refused vs answered)
- **a gold doc is among the answer's citations**

## Why this matters
85% of the golden set is answered *without a language model*: exactly, instantly, for free, and impossible to hallucinate. The LLM is only used where judgement or synthesis is needed. That's the main cost-control lever for a free public app.

Reproduce:
```bash
uv run irminsul-answer-eval --build data/build
```
