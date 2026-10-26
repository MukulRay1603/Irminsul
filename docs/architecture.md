# Irminsul v1 architecture

## 1. Data model: provenance on every record
Every record carries where it came from, how much to trust it, which game version it describes
and whether it's released (`src/irminsul/schema.py`).

| Field | Example | Used for |
|---|---|---|
| `source.url` | `https://gi.yatta.moe/en/archive/avatar/Raiden Shogun` | citations |
| `source.tier` | `official` / `rayy_verified` / `kqm` / `community` | ranking, labels in answers |
| `source.game_version` | `71F2` (live 7.1), a KQM commit SHA | freshness, changelogs |
| `release.status` | `released` / `announced` / `unknown` | the leak gate |
| `doc_id` | `character/raiden-shogun#overview` | stable upsert key, eval gold labels |

**Entities** (characters, weapons, artifact sets) hold exact facts:
- Lv90 stats, computed as base × growth curve + the ascension bonus for the phase reached
- talent scaling tables
- constellations
- R1–R5 passives
- set bonuses

**Docs** are the retrievable text rendered from entities and guides.

## 2. Sources and trust
| Tier | Source | Notes |
|---|---|---|
| official | Yatta API (live client text) | characters have official release timestamps |
| official | HoYoWiki (HoYoverse) | official name lists, announced characters, official videos |
| rayy_verified | team research notes (local only) | allowlisted files, claim-level tags, never published without approval |
| kqm | KQM Theorycrafting Library | CC BY-NC-SA 4.0, pinned to a commit |

## 3. The leak gate (`pipeline/gate.py`)
"Fail closed": when release status can't be proven, the record is dropped.
- `unknown` → dropped. A future release date → dropped.
- `announced` → allowed **only** from an official source. Only an overview doc is created
  (element, region, official description); kit modules are never ingested pre-release.
- Undated records (weapons, artifact sets) must appear in HoYoWiki's official lists. On Oct 26
  all 252 weapons and 63 sets matched the live data exactly.
- Third-party guides inherit release status from the official entity they're linked to: a KQM
  page about a character that isn't released is dropped.
- A manual `config/blocklist.txt` handles takedowns.

## 4. Corpus operations (`.github/workflows/corpus-update.yml`)
Weekly (or on patch day):
1. build
2. diff against the published manifest → changelog
3. **guards**: >10% record loss, any unverified record, or a big drop in docs fails the run
4. rebuild the index and **gate on retrieval hit@8 ≥ 0.90**
5. stage on a dated HF Dataset branch
6. open a review PR

Merging the PR promotes the staged build. Every failure opens an issue.

## 5. Retrieval (`retrieval/`)
- **Chunks:** ≤300 words, 40-word overlap. Each keeps its doc title and provenance.
- **Index:**
  - a folder: `chunks.jsonl`, `vectors.npy` (bge-small-en-v1.5, 384-d, ONNX) and a BM25 index
  - no vector DB: at ~3k chunks a dense query is a sub-millisecond matrix product
  - shipped with the dataset so the app never re-embeds on boot
- **Search:** BM25 + dense, fused with Reciprocal Rank Fusion (k=60), then a cross-encoder
  re-ranker (ms-marco-MiniLM-L-6-v2) over 20 candidates, reading the first 80 words of each.
  - That window was chosen by measurement: same hit@8 as full-chunk re-ranking at ~1/8 of the
    latency.

## 6. Answer engine (`engine/`)
Cheapest and safest first:

| Step | What | Cost |
|---|---|---|
| Guards | injection, leak words, versions beyond the announced one, other games, off-topic | free, deterministic |
| Cache | normalised question → answer | free |
| Exact | one named entity + stat/constellation/passive/set intent → answer from entity data | free, ~0.1 ms |
| Announced | named announced character → official overview only | free |
| RAG | hybrid search + re-rank → LLM with numbered sources, must cite `[n]` | LLM tokens |

**LLM router** (`engine/llm.py`):
- OpenAI-compatible client over free-tier providers
- a provider with no key is skipped; our own daily cap per provider stays below its free tier
- 429/5xx → cooldown and failover; all busy → a polite "busy" answer

**Trace:** route, retrieved doc ids and scores, provider/model, tokens, latency. It powers a
"why this answer?" view.

## 7. API (`api/`)
- `POST /ask`, `GET /health`. There are no admin endpoints.
- **Limits:**
  - per client: 6/min and 60/day, using X-Forwarded-For behind the Spaces proxy
  - a **global daily LLM budget**: when it's spent, free routes keep working and LLM questions
    get "busy"
- **Image:** python:3.12-slim + uv, no torch, ONNX models baked in, uid 1000. It loads the
  published corpus and index from the HF Dataset at boot.

## 8. Evaluation (`evals/`, `reports/`)
- **Golden set:** 107 items across 9 categories, with expectations as groups of acceptable
  phrasings. Every expected value is verified to appear in its gold doc.
- **Retrieval:** hit@k, recall@k, MRR, p50/p95, per category.
- **Answers:** route correctness, expected content, forbidden content, and **a gold doc must
  be cited**.

## 9. Key decisions
| Decision | Why |
|---|---|
| Embedded index instead of a hosted vector DB | small corpus; zero cost and no account; versioned with the data |
| Exact answers before the LLM | correct by construction, instant, free; 85% of the golden set needs no LLM |
| Deterministic guards before the LLM | can't be prompt-engineered away; costs nothing |
| Own small LLM router instead of a framework | four providers share one API; a small surface and fully testable |
| Stage → review PR → promote for data | a bad build never reaches users, and rollback is easy |
| Local-only team notes | private documents stay off the public dataset unless the owner approves |
