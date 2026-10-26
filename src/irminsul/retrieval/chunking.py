"""Split docs into retrievable chunks that keep their provenance.

Most docs are already section-sized. Longer ones are split on paragraph boundaries into
windows of about `max_words`, and every chunk repeats the doc title so it stays
self-explanatory when retrieved on its own.
"""

from collections.abc import Iterable

from pydantic import BaseModel

from irminsul.schema import Doc


class Chunk(BaseModel):
    chunk_id: str  # "<doc_id>::<n>"
    doc_id: str
    entity_id: str | None
    title: str
    text: str
    tier: str
    release_status: str
    source_url: str
    game_version: str | None = None


def _windows(paragraphs: list[str], max_words: int, overlap: int) -> list[str]:
    out: list[str] = []
    current: list[str] = []
    for para in paragraphs:
        words = para.split()
        if current and len(current) + len(words) > max_words:
            out.append(" ".join(current))
            current = current[-overlap:] if overlap else []
        while len(words) > max_words:  # a single huge paragraph
            out.append(" ".join(current + words[: max_words - len(current)]))
            words = words[max_words - len(current) :]
            current = []
        current += words
    if current:
        out.append(" ".join(current))
    return out


def chunk_doc(doc: Doc, max_words: int = 300, overlap: int = 40) -> list[Chunk]:
    lines = doc.text.splitlines()
    header = lines[0] if lines and lines[0].startswith("# ") else f"# {doc.title}"
    body = "\n".join(lines[1:] if lines and lines[0] == header else lines)
    # Paragraphs keep their line breaks so tables and lists survive inside a window.
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    pieces = []
    for para in paragraphs:
        if len(para.split()) <= max_words:
            pieces.append(para)
        else:
            pieces += [line for line in para.splitlines() if line.strip()]
    texts = _windows(pieces, max_words, overlap) or [""]
    return [
        Chunk(
            chunk_id=f"{doc.doc_id}::{n}",
            doc_id=doc.doc_id,
            entity_id=doc.entity_id,
            title=doc.title,
            text=f"{header}\n{text}".strip(),
            tier=doc.source.tier,
            release_status=doc.release.status,
            source_url=doc.source.url,
            game_version=doc.source.game_version,
        )
        for n, text in enumerate(texts)
    ]


def chunk_docs(docs: Iterable[Doc], max_words: int = 300, overlap: int = 40) -> list[Chunk]:
    return [c for d in docs for c in chunk_doc(d, max_words, overlap)]
