from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager
import logging
import time
from fastapi.responses import FileResponse
from rag import RAGChain

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

rag_chain: RAGChain = None


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
    title="LLMOps RAG API",
    description="Llama 3.1 8B QLoRA fine-tuned + Pinecone RAG",
    version="1.0.0",
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
    max_new_tokens: int = 512


class GenerateResponse(BaseModel):
    answer: str
    sources: list[str]
    latency_ms: float


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": rag_chain is not None and rag_chain.ready}

    
@app.get("/")
def ui():
    return FileResponse("index.html")


@app.post("/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    if not rag_chain or not rag_chain.ready:
        raise HTTPException(status_code=503, detail="Model not loaded yet")
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    start = time.time()
    answer, sources = rag_chain.query(req.query, top_k=req.top_k, max_new_tokens=req.max_new_tokens)
    latency_ms = (time.time() - start) * 1000

    return GenerateResponse(answer=answer, sources=sources, latency_ms=round(latency_ms, 1))


@app.post("/ingest")
def ingest(directory: str = "./docs"):
    """Ingest documents from a local directory into Pinecone."""
    from ingest import ingest_documents
    count = ingest_documents(directory)
    return {"ingested": count, "directory": directory}