"""
ingest.py — Load documents from a directory, chunk them, embed them, push to Pinecone.

Usage:
    python ingest.py --dir ./docs
    python ingest.py --dir ./docs --chunk-size 400 --chunk-overlap 50
"""

import os
import uuid
import argparse
import logging
from pathlib import Path

from dotenv import load_dotenv 

load_dotenv()                  

from pinecone import Pinecone, ServerlessSpec
from embedder import embed_texts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX   = os.getenv("PINECONE_INDEX", "llmops-rag")
EMBED_DIM        = 384   # all-MiniLM-L6-v2 output dim


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> list[str]:
    """Naive character-level chunker. Replace with sentence splitter if needed."""
    words = text.split()
    chunks, i = [], 0
    while i < len(words):
        chunk = " ".join(words[i : i + chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap
    return chunks


def load_documents(directory: str) -> list[dict]:
    """Load .txt and .md files recursively. Returns list of {source, text}."""
    docs = []
    for path in Path(directory).rglob("*"):
        if path.suffix in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if text:
                docs.append({"source": str(path), "text": text})
    logger.info(f"Loaded {len(docs)} documents from {directory}")
    return docs


def ensure_index(pc: Pinecone):
    existing = [idx.name for idx in pc.list_indexes()]
    if PINECONE_INDEX not in existing:
        logger.info(f"Creating index '{PINECONE_INDEX}'...")
        pc.create_index(
            name=PINECONE_INDEX,
            dimension=EMBED_DIM,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        logger.info("Index created.")
    else:
        logger.info(f"Index '{PINECONE_INDEX}' already exists.")


def ingest_documents(directory: str, chunk_size: int = 400, chunk_overlap: int = 50) -> int:
    if not PINECONE_API_KEY:
        raise EnvironmentError("PINECONE_API_KEY not set")

    pc = Pinecone(api_key=PINECONE_API_KEY)
    ensure_index(pc)
    index = pc.Index(PINECONE_INDEX)

    docs = load_documents(directory)
    if not docs:
        logger.warning("No documents found. Nothing ingested.")
        return 0

    all_chunks, all_meta = [], []
    for doc in docs:
        for chunk in chunk_text(doc["text"], chunk_size, chunk_overlap):
            all_chunks.append(chunk)
            all_meta.append({"source": doc["source"], "text": chunk})

    logger.info(f"Embedding {len(all_chunks)} chunks...")
    vectors = embed_texts(all_chunks)

    # Upsert in batches of 100
    BATCH = 100
    total = 0
    for i in range(0, len(all_chunks), BATCH):
        batch_vectors = [
            (str(uuid.uuid4()), vectors[j], all_meta[j])
            for j in range(i, min(i + BATCH, len(all_chunks)))
        ]
        index.upsert(vectors=batch_vectors)
        total += len(batch_vectors)
        logger.info(f"  Upserted {total}/{len(all_chunks)}")

    logger.info(f"Done. {total} vectors in Pinecone index '{PINECONE_INDEX}'.")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="./docs", help="Directory containing .txt/.md files")
    parser.add_argument("--chunk-size", type=int, default=400)
    parser.add_argument("--chunk-overlap", type=int, default=50)
    args = parser.parse_args()
    ingest_documents(args.dir, args.chunk_size, args.chunk_overlap)