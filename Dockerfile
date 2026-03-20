FROM python:3.12-slim

# System deps for bitsandbytes + torch
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY main.py rag.py embedder.py ingest.py guardrails.py index.html ./

# Model is NOT baked in — mount via Azure Blob or provide MODEL_PATH env var
# See README for options

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
