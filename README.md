# Irminsul v1 (work in progress)

A Genshin Impact assistant that answers from **official, version-tagged game data** and
cites its sources. The original v0 stack (QLoRA fine-tune + Pinecone RAG) is preserved at
the [`v0` release](https://github.com/MukulRay1603/Irminsul/releases/tag/v0).

## Status
**Phase 1, data foundation:**
- official in-game data (characters, weapons, artifact sets) from the Yatta API
- mechanics, frame data and findings from the KQM Theorycrafting Library (tier `kqm`)
- a leak gate that only lets released or officially announced content through
- deterministic, versioned corpus snapshots

## Develop
```bash
uv sync                      # create .venv with Python 3.12 + dev tools
uv run pytest                # tests run offline against saved API fixtures
uv run irminsul-build --limit 5 --cache data/cache   # small live build into data/build
uv run irminsul-build --sources kqm --cache data/cache   # one source only (default: all)
```

## Corpus pipeline
`fetch → leak gate → render docs → snapshot` (`src/irminsul/pipeline/`). Each snapshot
writes:
- `characters.jsonl`, `weapons.jsonl`, `artifact_sets.jsonl`: exact game facts
- `docs.jsonl`: retrievable text with stable ids and provenance (source URL, tier, game version, release status)
- `manifest.json`: counts, content hashes, and every dropped record with its reason

## Attribution
KQM docs are derived from the [KQM Theorycrafting Library](https://github.com/KQM-git/TCL)
by the KQM community, licensed under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Each doc links to the
source file at the exact TCL commit it was built from. The text is converted from MDX to plain
Markdown and split by section; derived KQM text keeps the same licence and must not be used
commercially.

Genshin Impact content and materials are trademarks and copyrights of HoYoverse. This is
an unofficial fan project, not affiliated with HoYoverse.
