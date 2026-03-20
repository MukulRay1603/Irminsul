import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from guardrails import validate_input, validate_output
from rag import RAGChain

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

rag_chain: Optional[RAGChain] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rag_chain
    logger.info("Loading RAG chain...")
    rag_chain = RAGChain()
    rag_chain.load()
    logger.info("RAG chain ready.")
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="Irminsul — Genshin Impact AI Assistant",
    description="RAG-powered assistant for Genshin Impact lore, builds, and mechanics.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    query: str
    top_k: int = 3


class GenerateResponse(BaseModel):
    answer: str
    sources: list[str]
    latency_ms: float
    blocked: bool = False


@app.get("/")
def ui():
    return FileResponse("index.html")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model_loaded": rag_chain is not None and rag_chain.ready,
    }


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    if not rag_chain or not rag_chain.ready:
        raise HTTPException(status_code=503, detail="Model not loaded yet.")

    allowed, reason = validate_input(req.query)
    if not allowed:
        return GenerateResponse(
            answer=reason,
            sources=[],
            latency_ms=0.0,
            blocked=True,
        )

    start = time.time()
    answer, sources = rag_chain.query(req.query, top_k=req.top_k)
    latency_ms = (time.time() - start) * 1000

    is_clean, answer = validate_output(answer)
    if not is_clean:
        return GenerateResponse(
            answer=answer,
            sources=[],
            latency_ms=round(latency_ms, 1),
            blocked=True,
        )

    return GenerateResponse(
        answer=answer,
        sources=sources,
        latency_ms=round(latency_ms, 1),
        blocked=False,
    )


@app.post("/ingest")
def ingest(directory: str = "./docs"):
    """Ingest documents from a local directory into Pinecone."""
    from ingest import ingest_documents
    count = ingest_documents(directory)
    return {"ingested": count, "directory": directory}