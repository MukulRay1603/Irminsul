# Irminsul v1 (work in progress)

A Genshin Impact assistant that answers from **official, version-tagged game data** and
cites its sources. The original v0 stack (QLoRA fine-tune + Pinecone RAG) is preserved at
the [`v0` release](https://github.com/MukulRay1603/Irminsul/releases/tag/v0).

## Status
**Phase 1, data foundation:**
- official in-game data (characters, weapons, artifact sets) from the Yatta API
- a leak gate that only lets released or officially announced content through
- deterministic, versioned corpus snapshots

## Develop
```bash
uv sync                      # create .venv with Python 3.12 + dev tools
uv run pytest                # tests run offline against saved API fixtures
uv run irminsul-build --limit 5 --cache data/cache   # small live build into data/build
```

## Corpus pipeline
`fetch → leak gate → render docs → snapshot` (`src/irminsul/pipeline/`). Each snapshot
writes:
- `characters.jsonl`, `weapons.jsonl`, `artifact_sets.jsonl`: exact game facts
- `docs.jsonl`: retrievable text with stable ids and provenance (source URL, tier, game version, release status)
- `manifest.json`: counts, content hashes, and every dropped record with its reason

Genshin Impact content and materials are trademarks and copyrights of HoYoverse. This is
an unofficial fan project, not affiliated with HoYoverse.
