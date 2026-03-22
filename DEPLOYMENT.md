# Deployment Guide

This document covers all deployment options for Irminsul, the cost tradeoffs between them, and the architectural decisions behind the live demo setup.

---

## Deployment Options

Irminsul supports two LLM backends and multiple hosting targets. Choose based on your infrastructure and budget.

| Backend | Where to Run | GPU Required | Cost |
|---|---|---|---|
| **Groq** (recommended) | Anywhere — no GPU | No | Free tier available |
| **Local Llama** (fine-tuned model) | Local machine / GPU VM | Yes (6GB+ VRAM) | Hardware cost / ~$0.50–1.50/hr on Azure |

---

## Live Demo: HuggingFace Spaces + Groq

**Why this is the live demo environment:**

The fine-tuned Llama 3.1 8B model is 16GB on disk and requires a GPU-enabled instance to serve at acceptable latency. On Azure, the minimum viable GPU instance for this model is the **NC4as T4 v3** (~$0.50/hr, ~$360/month). Running this persistently for a portfolio project is not cost-effective.

The live demo instead uses:
- **HuggingFace Spaces** — free CPU hosting for the FastAPI container
- **Groq API** — runs `llama-3.3-70b-versatile` on Groq's Language Processing Units (LPUs) at ~300 tokens/second, for free under the public tier

This demonstrates the identical RAG architecture — the LLM backend is swapped via a single environment variable (`LLM_BACKEND=groq`). The retrieval pipeline, guardrails, response format, and API contract are unchanged.

```
Live demo:  https://huggingface.co/spaces/MukulRay/Irminsul
```

---

## Option A: Local Development

The full stack including the fine-tuned model runs locally on an RTX 3060 6GB:

```bash
# 1. Clone and install
git clone https://github.com/MukulRay1603/Irminsul.git
cd Irminsul
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env — set MODEL_PATH, PINECONE_API_KEY

# 3. Ingest corpus
python ingest.py --dir ./docs --chunk-size 300 --chunk-overlap 40

# 4. Serve
uvicorn main:app --host 0.0.0.0 --port 8000
```

**Memory profile:**

| Component | VRAM |
|---|---|
| Llama 3.1 8B @ 4-bit NF4 | ~4.5 GB |
| all-MiniLM-L6-v2 embedder | ~90 MB |
| Inference headroom | ~1.2 GB |
| **Total** | **~5.8 GB** |

The model loads with `max_memory={0: "5.5GiB", "cpu": "24GiB"}` — layers that don't fit on GPU overflow to RAM automatically via `accelerate`.

---

## Option B: Docker (Local or Any Cloud)

The Dockerfile is intentionally slim — the model is **not baked in**. It's injected at runtime via `MODEL_PATH`.

```bash
# Build
docker build -t irminsul:latest .

# Run with Groq backend (no GPU needed)
docker run -p 8000:8000 \
  -e PINECONE_API_KEY=your_key \
  -e GROQ_API_KEY=your_key \
  -e PINECONE_INDEX=llmops-rag \
  -e LLM_BACKEND=groq \
  irminsul:latest

# Run with local model (GPU required)
docker run -p 8000:8000 \
  --gpus all \
  -v /path/to/models:/app/models \
  -e PINECONE_API_KEY=your_key \
  -e MODEL_PATH=/app/models/merged/exp2_lr2e-4_r16 \
  -e LLM_BACKEND=local \
  irminsul:latest
```

---

## Option C: Azure Container Apps

Azure Container Apps (ACA) is the production deployment target. The `deploy_azure.sh` script provisions the full stack in one command.

### Prerequisites

```bash
# Install Azure CLI
# macOS:
brew install azure-cli

# Linux:
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Windows: https://aka.ms/installazurecliwindows

# Log in
az login
az account show  # confirm your subscription
```

### One-shot deploy

```bash
export PINECONE_API_KEY=your_pinecone_key
export GROQ_API_KEY=your_groq_key
chmod +x deploy_azure.sh
./deploy_azure.sh
```

The script:
1. Creates resource group `irminsul-rg` in East US
2. Creates Azure Container Registry `irminsulacr`
3. Builds the Docker image via **ACR Tasks** — the source code is uploaded and built in Azure's cloud; no local Docker daemon needed
4. Creates a Container Apps environment
5. Deploys the app with secrets injected as environment variables
6. Outputs the live HTTPS URL

### Tearing down

```bash
# Delete everything — stops all billing immediately
az group delete --name irminsul-rg --yes --no-wait
```

### Cost breakdown (Groq backend, no GPU)

| Resource | SKU | Cost |
|---|---|---|
| Container Apps | Consumption plan | Free (180k vCPU-s/month) |
| ACR | Basic | ~$5/month |
| Outbound bandwidth | First 100GB | Free |
| **Total** | | **~$5/month** |

On Azure for Students ($100 credit), this runs for ~20 months.

### Why not GPU on Azure?

To serve the fine-tuned Llama model in production, a GPU instance is required:

| Instance | GPU | VRAM | Cost |
|---|---|---|---|
| NC4as T4 v3 | Tesla T4 | 16 GB | ~$0.50/hr = **~$360/month** |
| NC6s v3 | Tesla V100 | 16 GB | ~$0.90/hr = **~$648/month** |

At these prices, a portfolio project running 24/7 would exhaust the $100 student credit in under a week. The Groq backend delivers the same RAG functionality at zero marginal cost, making it the right engineering tradeoff.

### Serving the fine-tuned model on Azure (production path)

If cost were not a constraint, the correct architecture is:

1. **Upload model to Azure Blob Storage** (~$0.02/GB/month for 16GB = ~$0.32/month)
2. **Mount as a volume** in Container Apps — the container sees it at `/app/models/`
3. **Switch to GPU SKU** — replace `--cpu 1.0 --memory 2.0Gi` in `deploy_azure.sh` with a GPU-enabled workload profile
4. **Set `LLM_BACKEND=local`** in env vars

The Docker image and application code require zero changes for this path. The abstraction was designed for it.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `PINECONE_API_KEY` | Yes | — | Pinecone serverless API key |
| `PINECONE_INDEX` | No | `llmops-rag` | Pinecone index name |
| `LLM_BACKEND` | No | `groq` | `groq` or `local` |
| `GROQ_API_KEY` | If Groq | — | Groq API key |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | Groq model name |
| `MODEL_PATH` | If local | `./models/merged/exp2_lr2e-4_r16` | Path to merged model |
| `EMBED_MODEL` | No | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |

---

## CI/CD (Planned)

The intended CI/CD pipeline:

```
git push main
    │
    ▼
GitHub Actions
    ├── Run tests
    ├── Build Docker image
    ├── Push to ACR
    └── az containerapp update --image new-tag
```

This would give zero-downtime rolling deploys on every push to main. Currently, re-running `deploy_azure.sh` achieves the same result with a cold start.
