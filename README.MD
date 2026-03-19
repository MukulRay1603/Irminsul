# Irminsul

> Fine-tuned Llama 3.1 8B · QLoRA · Pinecone RAG · FastAPI · Azure Container Apps

A full end-to-end LLMOps serving stack — from a QLoRA fine-tuned model running in 4-bit NF4 on consumer hardware, through a retrieval-augmented generation pipeline, to a containerized API deployed on Azure. Built to be production-shaped, not just a demo.

**[→ Live Demo](https://mukulray1603.github.io/Irminsul/demo.html)**

---

## About Irminsul

Most LLM projects stop at inference. This one goes further:

- **Fine-tuned model** — Llama 3.1 8B fine-tuned with QLoRA (rank 16, lr 2e-4) on a custom dataset, merged and served locally in 4-bit NF4 quantization on an RTX 3060 6GB
- **RAG pipeline** — Documents ingested, chunked, embedded with `sentence-transformers/all-MiniLM-L6-v2` (fully local, zero API cost), and stored in Pinecone. Retrieval is semantic, top-k configurable at query time
- **Serving layer** — FastAPI with async lifespan model loading, typed Pydantic request/response models, CORS, health check, and a clean browser UI served from the same process
- **Containerized** — Dockerfile built for slim Python 3.12, model loaded at runtime via env-configurable path (not baked in)
- **Cloud-ready** — One-shot Azure deployment via ACR + Container Apps, with Pinecone key injected as a secret
- **Domain knowledge** — RAG corpus built around Genshin Impact lore, character builds, and elemental mechanics, serving as a rich real-world knowledge base for retrieval evaluation

---

## Architecture

```
User query
    │
    ▼
FastAPI  /generate
    │
    ├── Embed query (sentence-transformers, local)
    │       │
    │       ▼
    │   Pinecone — semantic search → top-k chunks
    │       │
    ▼       ▼
  LangChain RetrievalQA
    │
    ▼
Llama 3.1 8B (QLoRA fine-tuned, 4-bit NF4)
    │
    ▼
Grounded answer + source attribution
```

---

## Stack

| Layer | Technology |
|---|---|
| Base model | Llama 3.1 8B Instruct |
| Fine-tuning | QLoRA via PEFT (r=16, α=32, lr=2e-4) |
| Quantization | BitsAndBytes 4-bit NF4, bfloat16 compute |
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 |
| Vector DB | Pinecone (serverless, cosine similarity) |
| RAG chain | LangChain RetrievalQA |
| Serving | FastAPI + Uvicorn |
| Containerization | Docker (python:3.12-slim) |
| Cloud | Azure Container Apps + ACR |

---

## Quickstart

```bash
# 1. Clone and set up environment
git clone https://github.com/MukulRay1603/Irminsul.git
cd Irminsul
python -m venv venv && source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Fill in PINECONE_API_KEY in .env

# 3. Add your fine-tuned model
# Place merged model at: ./models/merged/exp2_lr2e-4_r16
# Or update MODEL_PATH in .env to point to your model

# 4. Ingest documents
python ingest.py --dir ./docs --chunk-size 300 --chunk-overlap 40

# 5. Start the server
uvicorn main:app --reload --port 8000

# UI available at http://localhost:8000
# API docs at http://localhost:8000/docs
```

---

## API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Browser UI |
| `GET` | `/health` | Model load status |
| `POST` | `/generate` | RAG query → grounded answer |
| `POST` | `/ingest` | Ingest docs from local directory |

**Example:**

```bash
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"query": "What weapons should Hu Tao use on a budget?", "top_k": 3}'
```

```json
{
  "answer": "For Hu Tao on a budget, Dragon's Bane is the strongest F2P option — it scales with Elemental Mastery and deals significant bonus damage on vaporized hits. White Tassel is the best 3-star alternative for pure Normal Attack scaling.",
  "sources": ["docs/character_builds.md"],
  "latency_ms": 4821.3
}
```

---

## Memory profile (RTX 3060 6GB)

| Component | VRAM |
|---|---|
| Llama 3.1 8B @ 4-bit NF4 | ~4.5 GB |
| all-MiniLM-L6-v2 embedder | ~90 MB |
| Inference headroom | ~1.2 GB |

Running the embedder on CPU frees ~90MB if needed — set `device_map="cpu"` in `rag.py`.

---

## Deploy to Azure

```bash
export PINECONE_API_KEY=your_key
chmod +x deploy_azure.sh
./deploy_azure.sh
```

The script provisions a resource group, builds and pushes the image via ACR Tasks (no local Docker build needed), creates a Container Apps environment, and deploys with the Pinecone key injected as a secret. Prints the live HTTPS endpoint on completion.

**Model in Azure:** The merged model (~16GB) isn't baked into the image. Recommended approach: mount from Azure Blob Storage as a volume for cheapest cold start on student credits.

---

## Project structure

```
Irminsul/
├── main.py           # FastAPI app — endpoints, lifespan, CORS
├── rag.py            # Model loading, 4-bit config, LangChain RAG chain
├── embedder.py       # sentence-transformers singleton wrapper
├── ingest.py         # Doc loader → chunker → Pinecone upsert
├── index.html        # Browser UI (dark theme, query history, source display)
├── Dockerfile
├── deploy_azure.sh   # One-shot Azure Container Apps deploy
├── requirements.txt
├── .env.example
└── docs/             # Corpus + GitHub Pages demo
    └── demo.html
```

---

## What's next

- [ ] Swap naive word chunker for `MarkdownHeaderTextSplitter` for better retrieval precision
- [ ] Add metadata filtering to Pinecone queries (filter by character, content type)
- [ ] Streaming response via SSE for lower perceived latency
- [ ] Expand corpus — per-character deep dives with stat thresholds and rotation guides
- [ ] CI/CD pipeline — GitHub Actions → ACR build → Container Apps deploy on push

---

Built while learning the full MLOps lifecycle — fine-tuning, quantization, retrieval, serving, and cloud deployment — on consumer hardware. Every component chosen deliberately, not for hype.
