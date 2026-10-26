# Irminsul v1 API image: CPU only, no torch (embeddings and re-ranking run on ONNX Runtime).
# Data is not baked in: set IRMINSUL_HF_DATASET (e.g. MukulRay/irminsul-corpus) to download
# the latest published corpus + index at boot, or mount folders via IRMINSUL_DATA/IRMINSUL_INDEX.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    IRMINSUL_MODEL_CACHE=/app/.models \
    IRMINSUL_CACHE=/tmp/irminsul \
    HOST=0.0.0.0 \
    PORT=7860

COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /usr/local/bin/uv
WORKDIR /app

# Dependencies first, for layer caching.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY config ./config
RUN uv sync --frozen --no-dev

# Bake the small ONNX models into the image so cold starts don't download them.
RUN uv run --no-sync python -c "from irminsul.retrieval.index import EMBED_MODEL, RERANK_MODEL, _embedder, _reranker; _embedder(EMBED_MODEL); _reranker(RERANK_MODEL)"

# Hugging Face Spaces run containers as uid 1000. The app runs as that non-root user; no
# secret is ever baked in (LLM keys and HF_TOKEN arrive as Space secrets at run time).
RUN useradd -m -u 1000 user && chown -R user /app
USER user

EXPOSE 7860
CMD ["uv", "run", "--no-sync", "irminsul-serve"]
