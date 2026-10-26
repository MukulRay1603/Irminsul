"""Retrieval tests with a tiny corpus and a fake embedder (no model downloads in CI)."""

from datetime import UTC, datetime

import numpy as np

from irminsul.retrieval.chunking import chunk_doc, chunk_docs
from irminsul.retrieval.index import HybridIndex
from irminsul.schema import Doc, Release, ReleaseStatus, SourceRef, Tier

NOW = datetime(2026, 10, 26, tzinfo=UTC)
VOCAB = ["raiden", "electro", "energy", "pity", "banner", "sword", "cryo", "stellar"]


class FakeEmbedder:
    """Bag-of-words vectors over a fixed vocabulary: deterministic and dependency-free."""

    def _vec(self, text: str) -> np.ndarray:
        words = text.lower().split()
        return np.array([sum(w.startswith(v) for w in words) for v in VOCAB], dtype=np.float32)

    def passage_embed(self, texts, batch_size=64):
        return [self._vec(t) for t in texts]

    def query_embed(self, texts):
        return [self._vec(t) for t in texts]


def doc(doc_id: str, text: str) -> Doc:
    return Doc(
        doc_id=doc_id,
        entity_id=None,
        kind="test",
        title=doc_id,
        text=text,
        release=Release(status=ReleaseStatus.RELEASED),
        source=SourceRef(
            source="t", url=f"https://example.org/{doc_id}", tier=Tier.OFFICIAL, fetched_at=NOW
        ),
    )


DOCS = [
    doc("raiden", "# Raiden Shogun\nElectro polearm. Her Burst restores Energy to the party."),
    doc("pity", "# Pity\nThe character event banner has a hard pity of 90 wishes."),
    doc("stellar", "# Stellar Conduct\nCryo and Electro make Stellar-Conduct."),
    doc("sword", "# Sacrificial Sword\nA 4-star sword that can reset its Skill cooldown."),
]


def test_short_docs_are_one_chunk_with_provenance():
    chunks = chunk_docs(DOCS)
    assert [c.chunk_id for c in chunks] == [f"{d.doc_id}::0" for d in DOCS]
    assert chunks[0].source_url == "https://example.org/raiden" and chunks[0].tier == "official"


def test_long_docs_split_with_title_on_every_chunk():
    body = "\n\n".join(f"Paragraph {i} " + "word " * 120 for i in range(6))
    chunks = chunk_doc(doc("long", f"# Long doc\n{body}"), max_words=300, overlap=40)
    assert len(chunks) > 1
    assert all(c.text.startswith("# Long doc") for c in chunks)
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_modes_find_the_right_doc(tmp_path):
    index = HybridIndex.build(chunk_docs(DOCS), embedder=FakeEmbedder())
    for mode in ("bm25", "dense", "hybrid"):
        assert index.search("hard pity on the banner", k=2, mode=mode)[0].chunk.doc_id == "pity"
    assert index.search("Raiden energy", k=1, mode="hybrid")[0].chunk.doc_id == "raiden"

    index.save(tmp_path / "idx")
    loaded = HybridIndex.load(tmp_path / "idx")
    loaded._embed = FakeEmbedder()
    assert loaded.search("stellar cryo", k=1)[0].chunk.doc_id == "stellar"
    assert len(loaded.chunks) == 4 and loaded.vectors.shape == (4, len(VOCAB))
