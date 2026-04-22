# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Irminsul is a production-shaped LLMOps stack demonstrating the full ML lifecycle: QLoRA fine-tuning (Llama 3.1 8B on Stanford Alpaca dataset), RAG retrieval pipeline, containerized FastAPI serving, and cloud deployment. The domain is Genshin Impact (used as a concrete, evaluable knowledge domain to test the pipeline).

**Key architectural decisions:**
- **Dual LLM backend**: Groq API (`llama-3.3-70b-versatile`) for the live demo vs. local fine-tuned Llama 3.1 8B, switchable via `LLM_BACKEND` env var
- **Web fallback**: When Pinecone corpus confidence is low (<0.35), fetches from wiki.gg/game8.co to answer the query
- **Guardrails-first**: Input validation (injection detection + domain cosine similarity) happens before any LLM call
- **Singleton embedder**: `embedder.py` uses a global instance loaded once, reused across all requests
- **Async lifespan**: Model loads once at FastAPI startup, not per-request

## Development Commands

### Local Development

```bash
# 1. Setup
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env — set PINECONE_API_KEY, GROQ_API_KEY (for Groq backend)
# Or set MODEL_PATH and LLM_BACKEND=local (for fine-tuned model)

# 3. Ingest corpus
python ingest.py --dir ./docs --chunk-size 300 --chunk-overlap 40

# 4. Run server
uvicorn main:app --reload --port 8000
# UI: http://localhost:8000
# API docs: http://localhost:8000/docs
```

### Docker

```bash
# Build
docker build -t irminsul:latest .

# Run with Groq backend (no GPU required)
docker run -p 8000:8000 \
  -e PINECONE_API_KEY=your_key \
  -e GROQ_API_KEY=your_key \
  -e LLM_BACKEND=groq \
  irminsul:latest

# Run with local model (GPU required, 6GB+ VRAM)
docker run -p 8000:8000 --gpus all \
  -v /path/to/models:/app/models \
  -e PINECONE_API_KEY=your_key \
  -e MODEL_PATH=/app/models/merged/exp2_lr2e-4_r16 \
  -e LLM_BACKEND=local \
  irminsul:latest
```

### Azure Deployment

```bash
export PINECONE_API_KEY=your_key
export GROQ_API_KEY=your_key
chmod +x deploy_azure.sh
./deploy_azure.sh
```

See `DEPLOYMENT.md` for full deployment guide and cost analysis.

## Architecture

### Request Flow

```
User Query
  ↓
Guardrails (injection detection + domain validation)
  ↓
FastAPI /generate endpoint
  ↓
Embed query (sentence-transformers, local CPU)
  ↓
Pinecone similarity search → top-k chunks
  ↓
Check corpus confidence (cosine score ≥ 0.35?)
  ├─ High confidence → RAG with corpus
  └─ Low confidence → Web fallback (wiki.gg)
       ↓
LangChain RetrievalQA (stuff chain)
  ↓
LLM Backend (Groq API OR local Llama 3.1 8B QLoRA)
  ↓
Grounded answer + source attribution
```

### Key Components

**main.py** — FastAPI app
- Async lifespan: loads RAG chain once at startup in `lifespan()` context manager
- Typed Pydantic models: `GenerateRequest`, `GenerateResponse` with `blocked` flag
- Endpoints: `/` (UI), `/health`, `/generate`, `/ingest`
- CORS enabled for cross-origin UI

**rag.py** — RAG orchestration
- `RAGChain` class with `.load()` and `.query()` methods
- `_build_groq_llm()` vs `_build_local_llm()` — backend selection
- Web fallback: `_fetch_wiki_page()` when `_corpus_has_coverage()` returns False
- Local model: 4-bit NF4 quantization via BitsAndBytes, loads to GPU with CPU overflow
- Prompts: `PROMPT_TEMPLATE` (corpus-grounded) vs `WEB_PROMPT_TEMPLATE` (live data)

**guardrails.py** — Input validation
- `validate_input()`: checks for injection patterns (`ignore previous instructions`, `act as`, etc.) + domain cosine similarity against `GENSHIN_ANCHORS`
- `validate_output()`: strips `</s>` tokens, length check
- Domain check uses same embedder as retrieval (singleton pattern)

**embedder.py** — Embedding singleton
- Loads `sentence-transformers/all-MiniLM-L6-v2` once via `get_embedder()` global
- Used by both ingestion and runtime retrieval
- Output: 384-dim vectors (fits Pinecone free tier)

**ingest.py** — Corpus ingestion
- `load_documents()`: recursively reads `.txt` and `.md` files
- `chunk_text()`: word-level chunking (configurable size/overlap)
- `ensure_index()`: creates Pinecone serverless index if missing
- `ingest_documents()`: embeds chunks, upserts to Pinecone in batches of 100

### Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `LLM_BACKEND` | No | `groq` | `groq` or `local` — switches LLM backend |
| `GROQ_API_KEY` | If Groq | — | Groq API key |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | Groq model name |
| `MODEL_PATH` | If local | `./models/merged/exp2_lr2e-4_r16` | Path to merged QLoRA model |
| `PINECONE_API_KEY` | Yes | — | Pinecone API key |
| `PINECONE_INDEX` | No | `llmops-rag` | Pinecone index name |
| `EMBED_MODEL` | No | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |

## Important Implementation Details

### Backend Switching

The system is designed to swap LLM backends without code changes. The only difference:
- **Groq**: Calls ChatGroq API, no local model loading
- **Local**: Loads Llama 3.1 8B from `MODEL_PATH` with 4-bit quantization

Both backends use identical RAG chain, retrieval, and response formatting.

### Web Fallback Logic

When corpus confidence is low (Pinecone top score < 0.35):
1. Extract subject from query via `_extract_subject()` (strips "build", "lore", etc.)
2. Fetch wiki.gg or game8.co page via `_fetch_wiki_page()`
3. If successful, bypass corpus RAG and answer directly from web content using `WEB_PROMPT_TEMPLATE`
4. Sources returned as `["web: wiki.gg/game8.co (live)"]`

This prevents the model from hallucinating when the corpus doesn't cover the query.

### Model Loading (Local Backend)

rag.py:140-176 shows the local model loading:
- `BitsAndBytesConfig`: 4-bit NF4 quantization, bfloat16 compute dtype
- `device_map="auto"`: automatic layer distribution across GPU/CPU
- `max_memory={0: "5.5GiB", "cpu": "24GiB"}`: limits GPU to 5.5GB (RTX 3060 6GB)
- Inference pipeline: `max_new_tokens=512`, `repetition_penalty=1.3`, greedy decoding

Total VRAM: ~5.8GB (model + embedder + overhead).

### Guardrails Implementation

guardrails.py implements two-layer validation:
1. **Injection detection** (pattern matching): blocks known jailbreak phrases
2. **Domain validation** (cosine similarity): query embedding vs. 16 Genshin-domain anchor sentences, threshold 0.15

If blocked, response has `blocked: true` and no LLM call is made.

### Corpus Pipeline

The knowledge corpus is maintained in a separate repository (`irminsul-corpus`) with a GitHub Actions workflow that runs weekly to pull fresh data and re-ingest to Pinecone. This repo only consumes the corpus, it doesn't manage it.

## Common Development Patterns

### Adding a New Endpoint

Edit `main.py` — follow existing patterns:
- Use Pydantic models for request/response
- Check `rag_chain.ready` before calling
- Return structured JSON, avoid raw strings

### Changing Chunk Strategy

Edit `ingest.py:chunk_text()` — current implementation is word-level. To use markdown-aware chunking:
```python
from langchain.text_splitter import MarkdownHeaderTextSplitter
# Replace chunk_text() with MarkdownHeaderTextSplitter logic
```

### Modifying Prompts

Edit `PROMPT_TEMPLATE` and `WEB_PROMPT_TEMPLATE` in `rag.py:30-79`. The prompts are character-themed ("Akasha") but follow strict formatting rules for builds/lore/mechanics.

### Adjusting Domain Validation

Edit `GENSHIN_ANCHORS` in `guardrails.py:10-27` to add/remove domain anchor sentences, or change the threshold in `guardrails.py:55` (default 0.15).

## Testing

The repository does not currently have automated tests. When adding tests:
- Mock the Pinecone client and embedder for unit tests
- Test guardrails independently from the RAG chain
- Integration tests should use a test Pinecone index

## Deployment Notes

- **Dockerfile** intentionally does NOT bake the model in — it's injected at runtime via volume mount or env var
- **deploy_azure.sh** uses ACR Tasks for cloud builds (no local Docker daemon needed)
- **Live demo** runs on HuggingFace Spaces with Groq backend to avoid GPU hosting costs (~$360/month for NC4as T4 v3)
- **GPU path** is fully supported but requires switching to GPU SKU in Azure Container Apps (see DEPLOYMENT.md)

## Related Resources

- Training notebook: https://colab.research.google.com/drive/1wXz6V196IXEEU3FKwxDJ7BBxRh79QqEF
- Corpus pipeline: https://github.com/MukulRay1603/irminsul-corpus
- Live demo: https://huggingface.co/spaces/MukulRay/Irminsul
