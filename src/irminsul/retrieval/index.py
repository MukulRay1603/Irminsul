"""An embedded hybrid index: BM25 + dense vectors in plain files, plus optional re-ranking.

At this corpus size (thousands of chunks) a flat numpy matrix answers a dense query in
well under a millisecond, so there is no vector database: the index is a folder that can
be built in CI and shipped with the dataset.

Search modes:
- "bm25": keyword search (exact names and numbers)
- "dense": embedding search (meaning, paraphrases)
- "hybrid": both, fused with Reciprocal Rank Fusion (RRF)
Any mode can be followed by a cross-encoder re-ranker over the top candidates.
"""

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import bm25s
import numpy as np

from irminsul.retrieval.chunking import Chunk
from irminsul.story import later

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"
RRF_K = 60
RERANK_WORDS = 80  # the cross-encoder reads only the start of each chunk: cost grows with length
MODEL_CACHE = os.environ.get("IRMINSUL_MODEL_CACHE")  # e.g. a folder on D:, not C:


def _embedder(model: str):
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=model, cache_dir=MODEL_CACHE)


def _reranker(model: str):
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name=model, cache_dir=MODEL_CACHE)


def _tokenize(texts: list[str]):
    return bm25s.tokenize(texts, stopwords="en", show_progress=False)


@dataclass
class Hit:
    chunk: Chunk
    score: float
    rank: int


class HybridIndex:
    def __init__(
        self, chunks: list[Chunk], vectors: np.ndarray, bm25: bm25s.BM25, embed_model: str
    ) -> None:
        self.chunks = chunks
        self.vectors = vectors
        self.bm25 = bm25
        self.embed_model = embed_model
        self._embed = None
        self._rerank = None
        self._rerank_model = RERANK_MODEL

    # ---- build / save / load -------------------------------------------------------
    @classmethod
    def build(
        cls, chunks: list[Chunk], embed_model: str = EMBED_MODEL, embedder=None
    ) -> "HybridIndex":
        """`embedder` can be injected (tests); it needs passage_embed and query_embed."""
        bm25 = bm25s.BM25()
        bm25.index(_tokenize([c.text for c in chunks]), show_progress=False)
        embedder = embedder or _embedder(embed_model)
        vectors = np.array(
            list(embedder.passage_embed([c.text for c in chunks], batch_size=64)),
            dtype=np.float32,
        )
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-12
        index = cls(chunks, vectors, bm25, embed_model)
        index._embed = embedder
        return index

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        with (path / "chunks.jsonl").open("w", encoding="utf-8") as f:
            for c in self.chunks:
                f.write(c.model_dump_json() + "\n")
        np.save(path / "vectors.npy", self.vectors)
        self.bm25.save(str(path / "bm25"))
        meta = {
            "embed_model": self.embed_model,
            "chunks": len(self.chunks),
            "dim": int(self.vectors.shape[1]),
        }
        (path / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "HybridIndex":
        meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        chunks = [
            Chunk.model_validate_json(line)
            for line in (path / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        return cls(
            chunks,
            np.load(path / "vectors.npy"),
            bm25s.BM25.load(str(path / "bm25")),
            meta["embed_model"],
        )

    # ---- search --------------------------------------------------------------------
    def _bm25_ranking(self, query: str, n: int) -> list[int]:
        results, scores = self.bm25.retrieve(
            _tokenize([query]), k=min(n, len(self.chunks)), show_progress=False
        )
        return [int(i) for i, s in zip(results[0], scores[0], strict=True) if s > 0]

    def _dense_ranking(self, query: str, n: int) -> list[int]:
        if self._embed is None:
            self._embed = _embedder(self.embed_model)
        q = np.array(next(iter(self._embed.query_embed([query]))), dtype=np.float32)
        q /= np.linalg.norm(q) + 1e-12
        sims = self.vectors @ q
        top = np.argpartition(-sims, min(n, len(sims) - 1))[:n]
        return [int(i) for i in top[np.argsort(-sims[top])]]

    def search(
        self,
        query: str,
        k: int = 8,
        mode: str = "hybrid",
        rerank: bool = False,
        candidates: int = 20,
        rerank_words: int = RERANK_WORDS,
        exclude_tiers: frozenset[str] = frozenset(),
        max_revealed: str | None = None,
        report: dict | None = None,
    ) -> list[Hit]:
        """Top-k chunks; chunks whose tier is in `exclude_tiers` are never returned.

        `max_revealed` (story-safe mode) also drops every chunk revealed in a later game
        version, before re-ranking, so neither the re-ranker nor the LLM ever sees it.
        `report`, if given, receives {"hidden": <candidates dropped by that filter>}.
        """
        n = max(candidates, k)
        # Dig deeper so filtering still leaves n; a story filter can hide a lot of lore.
        pool = n * 4 if max_revealed else n * 2 if exclude_tiers else n
        if mode == "bm25":
            fused = {i: 1.0 / (r + 1) for r, i in enumerate(self._bm25_ranking(query, pool))}
        elif mode == "dense":
            fused = {i: 1.0 / (r + 1) for r, i in enumerate(self._dense_ranking(query, pool))}
        elif mode == "hybrid":
            fused: dict[int, float] = {}
            for ranking in (self._bm25_ranking(query, pool), self._dense_ranking(query, pool)):
                for r, i in enumerate(ranking):
                    fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + r + 1)
        else:
            raise ValueError(f"unknown mode {mode!r}")
        allowed = [i for i in fused if self.chunks[i].tier not in exclude_tiers]
        if max_revealed:
            visible = [i for i in allowed if not later(self.chunks[i].revealed_in, max_revealed)]
            if report is not None:
                report["hidden"] = len(allowed) - len(visible)
            allowed = visible
        order = sorted(allowed, key=fused.get, reverse=True)[:n]
        if rerank and order:
            if self._rerank is None:
                self._rerank = _reranker(self._rerank_model)
            passages = [" ".join(self.chunks[i].text.split()[:rerank_words]) for i in order]
            scores = list(self._rerank.rerank(query, passages))
            ranked = sorted(zip(order, scores, strict=True), key=lambda x: x[1], reverse=True)
        else:
            ranked = [(i, fused[i]) for i in order]
        return [Hit(self.chunks[i], float(s), r) for r, (i, s) in enumerate(ranked[:k])]


def timed_search(index: HybridIndex, query: str, **kwargs) -> tuple[list[Hit], float]:
    start = time.perf_counter()
    hits = index.search(query, **kwargs)
    return hits, (time.perf_counter() - start) * 1000
