"""FastAPI app: POST /ask and GET /health. No admin or ingest endpoints by design.

The engine and limits are injected (`create_app`) so tests run without data or models.
"""

import json
from dataclasses import asdict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from irminsul.api.limits import Limits
from irminsul.engine.engine import Engine
from irminsul.engine.guards import MAX_CHARS


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_CHARS)


class CitationOut(BaseModel):
    n: int
    title: str
    url: str
    tier: str
    doc_id: str | None = None


class AskResponse(BaseModel):
    answer: str
    route: str
    citations: list[CitationOut]
    trace: dict


def client_id(request: Request) -> str:
    # Behind the HF Spaces proxy the real client is the first X-Forwarded-For address.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "?")


def create_app(engine: Engine, limits: Limits | None = None, meta: dict | None = None) -> FastAPI:
    limits = limits or Limits()
    app = FastAPI(
        title="Irminsul",
        version="1.0.0a0",
        description="Genshin Impact answers from official, version-tagged data.",
    )

    @app.get("/health")
    def health() -> dict:
        providers = []
        if engine.llm is not None and hasattr(engine.llm, "providers"):
            providers = [
                {"name": p.name, "configured": bool(p.api_key)} for p in engine.llm.providers
            ]
        return {
            "status": "ok",
            "corpus": meta or {},
            "entities": len(engine.store.by_id),
            "index_chunks": len(getattr(engine.index, "chunks", [])),
            "llm_providers": providers,
            "limits": limits.snapshot(),
        }

    @app.post("/ask/stream")
    def ask_stream(body: AskRequest, request: Request):
        """Server-sent events: `meta` (route + candidate citations), `delta` (text chunks),
        `done` (final route, the citations actually used, trace)."""
        if reason := limits.allow(client_id(request)):
            return JSONResponse(status_code=429, content={"detail": reason})
        allow_llm = limits.llm_budget_left()

        def events():
            for kind, payload in engine.ask_stream(body.question, allow_llm=allow_llm):
                if (
                    kind == "done"
                    and payload["route"] == "rag"
                    and payload["trace"].get("cache") != "hit"
                ):
                    limits.spend_llm()
                yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/ask", response_model=AskResponse)
    def ask(body: AskRequest, request: Request):
        if reason := limits.allow(client_id(request)):
            return JSONResponse(status_code=429, content={"detail": reason})
        # Once the daily LLM budget is spent, free routes still work and LLM questions get "busy".
        allow_llm = limits.llm_budget_left()
        answer = engine.ask(body.question, allow_llm=allow_llm)
        if answer.route == "rag" and answer.trace.get("cache") != "hit":
            limits.spend_llm()
        return AskResponse(
            answer=answer.text,
            route=answer.route,
            citations=[CitationOut(**asdict(c)) for c in answer.citations],
            trace=answer.trace,
        )

    return app
