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

    def quota_for(cid: str) -> dict:
        snap = limits.snapshot()
        return {
            "resin": limits.resin(cid),
            "world": {
                "left": max(0, snap["llm_per_day"] - snap["llm_used_today"]),
                "per_day": snap["llm_per_day"],
                "resets_in_s": snap["llm_resets_in_s"],
            },
        }

    @app.get("/quota")
    def quota(request: Request) -> dict:
        """The caller's Resin (AI answers they can still ask for) and the shared daily budget."""
        return quota_for(client_id(request))

    def spend(cid: str, route: str, trace: dict) -> None:
        # Only fresh AI-written answers cost anything; exact answers, cache hits and refusals
        # are free for the player and for the budget.
        if route == "rag" and trace.get("cache") != "hit":
            limits.spend_llm()
            limits.spend_resin(cid)

    @app.post("/ask/stream")
    def ask_stream(body: AskRequest, request: Request):
        """Server-sent events: `meta` (route + candidate citations), `delta` (text chunks),
        `done` (final route, the citations actually used, trace, and the caller's quota)."""
        cid = client_id(request)
        if reason := limits.allow(cid):
            return JSONResponse(status_code=429, content={"detail": reason})
        allow_llm = limits.llm_budget_left()
        out_of_resin = not limits.has_resin(cid)

        def events():
            for kind, payload in engine.ask_stream(
                body.question, allow_llm=allow_llm, out_of_resin=out_of_resin
            ):
                if kind == "done":
                    spend(cid, payload["route"], payload["trace"])
                    payload = {**payload, "quota": quota_for(cid)}
                yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/ask", response_model=AskResponse)
    def ask(body: AskRequest, request: Request):
        cid = client_id(request)
        if reason := limits.allow(cid):
            return JSONResponse(status_code=429, content={"detail": reason})
        # Once the daily LLM budget or the player's Resin is spent, free routes still work
        # and LLM questions get a polite reply instead.
        allow_llm = limits.llm_budget_left()
        answer = engine.ask(
            body.question, allow_llm=allow_llm, out_of_resin=not limits.has_resin(cid)
        )
        spend(cid, answer.route, answer.trace)
        return AskResponse(
            answer=answer.text,
            route=answer.route,
            citations=[CitationOut(**asdict(c)) for c in answer.citations],
            trace=answer.trace,
        )

    return app
