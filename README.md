<div align="center">

<img src="Images\Banner.png" alt="Irminsul Banner" width="100%">
<!-- PLACEHOLDER: Add a banner image. Recommended: 1280x320px, dark green/Dendro aesthetic.
     Save as assets/banner.png. Tools: Figma, Canva, or a cropped screenshot of the UI. -->

# Irminsul

**A production-shaped LLMOps stack — QLoRA fine-tuning on Colab, RAG pipeline, containerized serving, and cloud deployment.**

[![Live Demo](https://img.shields.io/badge/Live_Demo-HuggingFace_Spaces-FFD21E?style=flat&logo=huggingface)](https://huggingface.co/spaces/MukulRay/Irminsul)
[![GitHub](https://img.shields.io/badge/GitHub-MukulRay1603-181717?style=flat&logo=github)](https://github.com/MukulRay1603/Irminsul)
[![Corpus Pipeline](https://img.shields.io/badge/Corpus_Pipeline-irminsul--corpus-2ea44f?style=flat&logo=github)](https://github.com/MukulRay1603/irminsul-corpus)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat)](LICENSE)

</div>

---

Most LLM projects stop at inference. This one builds the full stack: a QLoRA fine-tuned Llama 3.1 8B served through a RAG pipeline, with guardrails, a domain-specific knowledge base, and a containerized FastAPI server designed for cloud deployment.

**[→ Try the live demo](https://huggingface.co/spaces/MukulRay/Irminsul)**

---

## About Irminsul

Irminsul is a domain-specific AI assistant for Genshin Impact — built not because Genshin needed an AI assistant, but because it provided a concrete, evaluable knowledge domain to build an LLMOps pipeline around. Every component was chosen deliberately:

- A knowledge domain rich enough to evaluate retrieval quality (characters, mechanics, lore)
- Ground truth data available (KQM Theorycrafting Library, game stat APIs) to measure hallucination
- Community signal data (patch notes, meta shifts) to test corpus freshness

The domain is the test harness. The pipeline is the project.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Query                              │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Guardrails Layer                             │
│  • Injection detection (pattern matching)                       │
│  • Domain validation (cosine similarity vs anchor embeddings)   │
│  • Output sanitization                                          │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                  FastAPI /generate                               │
└──────────┬──────────────────────────────────────────────────────┘
           │
           ├─── Embed query (sentence-transformers, local, CPU)
           │              │
           │              ▼
           │         Pinecone ── semantic search ──► top-k chunks
           │              │
           ▼              ▼
    LangChain RetrievalQA (stuff chain)
           │
           ▼
  ┌────────────────────────────────────┐
  │         LLM Backend                │
  │                                    │
  │  Groq (live demo)                  │
  │  llama-3.3-70b-versatile           │
  │  ~300 tok/s, free tier             │
  │             ──── OR ────           │
  │  Local (fine-tuned)                │
  │  Llama 3.1 8B QLoRA               │
  │  4-bit NF4, RTX 3060 6GB          │
  │  (inference only — trained on     │
  │   Colab A100)                     │
  └────────────────────────────────────┘
           │
           ▼
    Grounded answer + source attribution
```

---

## Components

### Fine-Tuned Model

Llama 3.1 8B Instruct fine-tuned with QLoRA on the Stanford Alpaca dataset (52K instruction-following examples), trained on Google Colab Pro (A100). Local inference runs in 4-bit NF4 quantization on an RTX 3060 6GB.

**[→ View training notebook on Colab](https://colab.research.google.com/drive/1wXz6V196IXEEU3FKwxDJ7BBxRh79QqEF?usp=sharing)**
<!-- PLACEHOLDER: Replace YOUR_NOTEBOOK_LINK_HERE with your actual Colab share link
     File → Share → Copy link (set to "Anyone with the link can view") -->

| Parameter | Value |
|---|---|
| Base model | `meta-llama/Llama-3.1-8B-Instruct` |
| Dataset | Stanford Alpaca (`tatsu-lab/alpaca`, 52K examples) |
| Method | QLoRA via PEFT |
| Rank / Alpha | r=16, α=32, dropout=0.05 |
| Target modules | q_proj, v_proj, k_proj, o_proj |
| Learning rate | 2e-4 (cosine schedule, warmup 3%) |
| Batch size | 4 per device × 4 grad accumulation = effective 16 |
| Epochs | 2 |
| Optimizer | paged_adamw_32bit |
| Quantization (inference) | 4-bit NF4, bfloat16 compute dtype |
| Training infra | Google Colab Pro (A100 40GB) |
| Experiment tracking | MLflow (3 runs) |

**[→ Download exp2_lr2e-4_r16 model ](https://drive.google.com/drive/folders/1vAVXDXzT5lThnvlgQwXRi0ParmyB3V0P?usp=sharing)**

Three experiments run sequentially, each tracked in MLflow:

| Experiment | LR | Rank | Result |
|---|---|---|---|
| exp1_lr1e-4_r16 | 1e-4 | 16 | Conservative baseline |
| exp2_lr2e-4_r16 | 2e-4 | 16 | **Winner** — best loss/quality balance |
| exp3_lr2e-4_r8 | 2e-4 | 8 | Tests if rank=16 is worth the extra params |

Winning checkpoint (`exp2_lr2e-4_r16`) selected by faithfulness (0.826) and ROUGE-L (0.466), both computed locally via cosine similarity and token overlap against a held-out eval set.

<!-- PLACEHOLDER: Add MLflow experiment screenshot here — images/mlflow_runs.png -->

### RAG Pipeline

Documents are chunked, embedded locally with `sentence-transformers/all-MiniLM-L6-v2` (384-dim, zero API cost), and stored in Pinecone serverless. Retrieval is semantic, top-k configurable per query.

| Component | Choice | Reason |
|---|---|---|
| Embedder | all-MiniLM-L6-v2 | Runs locally, strong semantic retrieval, 384-dim fits free Pinecone tier |
| Vector DB | Pinecone serverless | Zero ops, cosine similarity, free tier sufficient for corpus size |
| Chunking | Word-level, 300 words, 40-word overlap | Preserves semantic units across chunk boundaries |
| Chain | LangChain RetrievalQA (stuff) | Simple, inspectable, returns source documents |

### Knowledge Corpus

Corpus is maintained in a [separate repository](https://github.com/MukulRay1603/irminsul-corpus) with an autonomous update pipeline. It ingests from three tiers of sources with different trust levels:

| Tier | Source | Files | Trust |
|---|---|---|---|
| 1 — Ground Truth | KQM Theorycrafting Library (peer-reviewed mechanics) | ~305 | Highest — cite in builds |
| 1 — Ground Truth | genshin-db API (exact character/weapon/artifact stats) | ~406 | Highest — exact game data |
| 2 — Expert Synthesis | Gemini-authored prose grounded in Tier 1 | ~83 | High — no hallucinated stats |
| 3 — Community Signal | Official patch notes, banner history, event calendar | ~80 | Medium — tagged explicitly |

A GitHub Actions workflow runs every Sunday at 2am UTC, pulls fresh data, commits the docs, and re-ingests ~4,000 vectors to Pinecone automatically.

### Guardrails

Two layers of input validation before any LLM call:

1. **Injection detection** — pattern matching against known jailbreak phrases (`ignore previous instructions`, `act as`, `DAN mode`, etc.)
2. **Domain validation** — cosine similarity between the query embedding and a set of Genshin-domain anchor sentences. Queries scoring below threshold (0.35) are rejected with a domain-scoped error message before touching the LLM.

Output is sanitized to strip generation artifacts (`</s>` tokens, trailing whitespace) and length-checked.

### Serving Layer

FastAPI with:
- Async lifespan model loading (model loads once at startup, not per request)
- Typed Pydantic request/response models with `blocked` flag for guardrail rejections
- CORS enabled for cross-origin UI
- `/health` endpoint reporting model load status
- Browser UI served from the same process (no separate frontend server)

---

## Stack

| Layer | Technology |
|---|---|
| Base model | Llama 3.1 8B Instruct |
| Fine-tuning | QLoRA via PEFT (r=16, α=32, lr=2e-4) |
| Experiment tracking | MLflow |
| Quantization | BitsAndBytes 4-bit NF4, bfloat16 compute |
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 |
| Vector DB | Pinecone serverless (cosine, 384-dim) |
| RAG chain | LangChain RetrievalQA |
| Serving | FastAPI + Uvicorn |
| Containerization | Docker (python:3.12-slim) |
| Live demo hosting | HuggingFace Spaces (CPU Basic) |
| Production deployment | Azure Container Apps + ACR |
| LLM backend (demo) | Groq API (llama-3.3-70b-versatile) |
| Corpus pipeline | GitHub Actions (weekly, autonomous) |

---

## Quickstart

### Option 1 — Groq backend (no GPU required)

```bash
# 1. Clone
git clone https://github.com/MukulRay1603/Irminsul.git
cd Irminsul

# 2. Install
python -m venv venv && source venv/bin/activate
# Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Set PINECONE_API_KEY and GROQ_API_KEY in .env
# LLM_BACKEND=groq is the default

# 4. Ingest corpus (or use pre-ingested Pinecone index)
python ingest.py --dir ./docs --chunk-size 300 --chunk-overlap 40

# 5. Run
uvicorn main:app --reload --port 8000
# UI: http://localhost:8000
# API docs: http://localhost:8000/docs
```

### Option 2 — Local fine-tuned model (GPU required for inference, 6GB+ VRAM)

```bash
# Same steps 1–3, then:
# Set LLM_BACKEND=local and MODEL_PATH in .env

# 4. Download model
# Place the merged QLoRA model at: ./models/merged/exp2_lr2e-4_r16/
# (Or update MODEL_PATH in .env)

# 5. Run
uvicorn main:app --reload --port 8000
```

### Docker

```bash
# Groq backend (no GPU)
docker build -t irminsul:latest .
docker run -p 8000:8000 \
  -e PINECONE_API_KEY=your_key \
  -e GROQ_API_KEY=your_key \
  -e LLM_BACKEND=groq \
  irminsul:latest
```

---

## API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Browser UI |
| `GET` | `/health` | Model load status + ready flag |
| `POST` | `/generate` | RAG query → grounded answer + sources |
| `POST` | `/ingest` | Ingest docs from a local directory path |

**Request:**
```json
{
  "query": "What weapons should Hu Tao use on a budget?",
  "top_k": 3
}
```

**Response:**
```json
{
  "answer": "For Hu Tao on a budget, Dragon's Bane is the strongest F2P option — it scales with Elemental Mastery and deals significant bonus damage on vaporized hits. White Tassel is the best 3-star alternative for pure Normal Attack scaling.",
  "sources": ["docs/generated/characters/hu_tao.md", "docs/tcl/characters/pyro/hutao.md"],
  "latency_ms": 1240.5,
  "blocked": false
}
```

If a query is rejected by guardrails, `blocked: true` is returned with the rejection reason in `answer`. No LLM call is made.

---

## Deployment

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for the full guide covering:

- Local development setup
- Docker (local and cloud)
- Azure Container Apps (one-shot `deploy_azure.sh`)
- Cost breakdown and the reasoning behind the demo setup
- GPU serving path for the fine-tuned model

**Why the live demo runs on HuggingFace + Groq, not Azure GPU:**

Serving the fine-tuned Llama 3.1 8B requires a GPU instance. The minimum viable option on Azure (NC4as T4 v3) costs ~$360/month — not justified for a portfolio project. The Dockerfile and `deploy_azure.sh` are written for the Azure path; the live demo swaps the LLM backend to Groq via a single environment variable. The RAG pipeline, guardrails, and serving layer are identical.

---

## Project Structure

```
Irminsul/
├── main.py                  # FastAPI app: endpoints, lifespan, CORS, response models
├── rag.py                   # LangChain RAG chain, dual backend (Groq / local Llama)
├── embedder.py              # sentence-transformers singleton (loads once, reused)
├── ingest.py                # Doc loader → word chunker → Pinecone upsert
├── guardrails.py            # Input validation: injection detection + domain cosine check
├── index.html               # Browser UI: dark Dendro theme, query history, source display
│
├── LLMOps_Pipeline.ipynb    # Full training notebook: QLoRA, MLflow, eval (Colab A100)
│
├── Dockerfile               # python:3.12-slim, model NOT baked in
├── deploy_azure.sh          # One-shot ACR build + Container Apps deploy
├── .env.example             # Environment variable reference
│
├── DEPLOYMENT.md            # Full deployment guide + cost analysis
├── requirements.txt
├── assets/                  # Screenshots and assets used in this README
│   ├── banner.png
│   ├── ui_main.png
│   ├── ui_response.png
│   └── mlflow_runs.png
└── models/                  # gitignored — place merged model here locally
    └── merged/
        └── exp2_lr2e-4_r16/
```

---

## Evaluation

Winning checkpoint evaluated against a held-out set using a custom local eval (cosine similarity for faithfulness, token overlap for ROUGE-L). RAGAS was attempted but hit async timeout issues on Colab — custom eval used instead, results are fully reproducible from the notebook.

| Metric | Score | Method |
|---|---|---|
| Faithfulness | 0.826 | Cosine similarity: ground truth → answer embedding |
| ROUGE-L | 0.466 | Token overlap vs reference answers |

Full RAG pipeline evaluation (context recall, answer relevance) is a planned addition — see [What's Next](#whats-next).

---

## Screenshots

<!-- PLACEHOLDER: Add screenshots once you have them.
     Save to assets/ and uncomment these lines:

![Irminsul UI](assets/ui_main.png)
![Response with sources](assets/ui_response.png)
![MLflow experiment runs](assets/mlflow_runs.png)

     Tips:
     - ui_main.png: screenshot of http://localhost:8000 before any query
     - ui_response.png: run a query so the answer + sources section is visible
     - mlflow_runs.png: Colab experiment comparison table showing 3 runs + metrics
-->

*Screenshots coming soon — [try the live demo](https://huggingface.co/spaces/MukulRay/Irminsul) to see it in action.*

---

## What's Next

- [ ] **RAGAS evaluation** — systematic RAG eval (faithfulness, context recall, answer relevance) on a held-out question set
- [ ] **MarkdownHeaderTextSplitter** — replace naive word chunker for section-aware chunking that respects document structure
- [ ] **Metadata filtering** — filter Pinecone queries by character, content tier, or topic category
- [ ] **Streaming responses** — SSE for lower perceived latency on long answers
- [ ] **CI/CD pipeline** — GitHub Actions → ACR build → `az containerapp update` on push to main
- [ ] **Corpus expansion** — constellation effects, rotation guides, and ER/EM thresholds per character

---

## Related: irminsul-corpus

The knowledge base is maintained in a companion repository:

**[MukulRay1603/irminsul-corpus](https://github.com/MukulRay1603/irminsul-corpus)**

It runs a fully autonomous weekly pipeline: pulls fresh game data from the KQM Theorycrafting Library and genshin-db API, synthesizes prose with Gemini 2.5 Flash, commits ~800 documents to the repo, and re-ingests ~4,000 vectors to Pinecone — without any manual intervention.

---

## License

MIT — see [LICENSE](LICENSE) for details.

Genshin Impact is owned by HoYoverse. This project is not affiliated with or endorsed by HoYoverse.

---

<div align="center">

Built to learn the full MLOps lifecycle — fine-tuning on Colab, quantized inference on consumer hardware, retrieval, serving, and cloud deployment. Every component chosen deliberately, not for hype.

</div>