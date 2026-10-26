"""FastAPI app: POST /ask and GET /health. No admin or ingest endpoints by design.

The engine and limits are injected (`create_app`) so tests run without data or models.
Hardening for a public endpoint lives here too (see docs/security.md): the client id used by
every limit, a raw body cap, security headers, closed CORS and errors without internals.
"""

import ipaddress
import json
import logging
import os
from collections.abc import Iterator
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from irminsul.api.limits import Limits
from irminsul.engine.engine import Engine
from irminsul.engine.guards import MAX_CHARS

log = logging.getLogger("irminsul.api")

# A question is at most MAX_CHARS characters (4 bytes each in UTF-8) plus a little JSON.
MAX_BODY_BYTES = 8 * 1024
ERROR_DETAIL = "Something went wrong on our side. Please try again."

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data: https://i.ytimg.com",
        "frame-src https://www.youtube-nocookie.com",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
    ]
)
# FastAPI's /docs and /redoc pages load Swagger UI / ReDoc from jsDelivr with an inline script.
DOCS_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly",
        "worker-src 'self' blob:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
    ]
)
DOCS_PATHS = ("/docs", "/redoc")
PERMISSIONS_POLICY = (
    "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"
)


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


def client_id(request: Request, trusted_hops: int = 0) -> str:
    """The address every per-client limit (burst, daily cap, Resin) is keyed on.

    X-Forwarded-For is written by the client first and each proxy appends the address it saw,
    so only the right-most `trusted_hops` entries are ours: with one proxy in front (HF
    Spaces), the client is the last entry. Anything further left can be forged, so it is never
    used. With 0 hops (the default) the header is ignored and the socket peer is the client.
    IPv6 addresses are grouped by /64, the block a single subscriber usually gets.
    """
    peer = request.client.host if request.client else "?"
    if trusted_hops > 0:
        chain = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",")]
        chain = [h for h in chain if h]
        # Fewer entries than proxies means the request skipped a proxy: use the socket peer.
        peer = chain[-trusted_hops] if len(chain) >= trusted_hops else peer
    return _group_address(peer)


def _group_address(host: str) -> str:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return host  # e.g. "testclient" under Starlette's TestClient
    if addr.version == 4:
        return str(addr)
    if addr.ipv4_mapped is not None:
        return str(addr.ipv4_mapped)
    return str(ipaddress.ip_network(f"{addr}/64", strict=False))


def trusted_proxy_hops() -> int:
    """IRMINSUL_TRUSTED_PROXY_HOPS: proxies in front of the app that append X-Forwarded-For.

    0 (default) trusts no header. Set 1 on Hugging Face Spaces, which sits behind one proxy.
    """
    return max(0, int(os.environ.get("IRMINSUL_TRUSTED_PROXY_HOPS", "0")))


def cors_origins() -> list[str]:
    """IRMINSUL_CORS_ORIGINS: comma-separated origins allowed to call the API from a browser.

    Empty (default) adds no CORS headers, so only same-origin pages can read responses.
    """
    raw = os.environ.get("IRMINSUL_CORS_ORIGINS", "")
    return [o.strip() for o in raw.split(",") if o.strip() and o.strip() != "*"]


class BodyLimit:
    """Reject request bodies over `max_bytes` with 413, before they are buffered in full.

    Pydantic caps the question itself; this caps the raw bytes, chunked uploads included.
    """

    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None:
            if not length.isdigit():
                return await _plain(send, 400, "Invalid Content-Length.")
            if int(length) > self.max_bytes:
                return await _plain(send, 413, "Request body too large.")
        received = 0

        async def limited():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # FastAPI re-raises HTTPException from body parsing, so this becomes a 413.
                    raise HTTPException(413, "Request body too large.")
            return message

        await self.app(scope, limited, send)


async def _plain(send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class SecurityHeaders:
    """Add security headers to every response (a pure ASGI wrapper, so SSE still streams)."""

    def __init__(self, app, frame_ancestors: str = "'none'") -> None:
        self.app = app
        self.frame_ancestors = frame_ancestors

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        docs = scope["path"].startswith(DOCS_PATHS)
        csp = f"{DOCS_CSP if docs else CSP}; frame-ancestors {self.frame_ancestors}"
        extra = [
            (b"content-security-policy", csp.encode()),
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"permissions-policy", PERMISSIONS_POLICY.encode()),
            (b"cross-origin-opener-policy", b"same-origin"),
        ]
        if self.frame_ancestors == "'none'":
            extra.append((b"x-frame-options", b"DENY"))

        async def with_headers(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.app(scope, receive, with_headers)


def sse_events(
    engine: Engine, limits: Limits, cid: str, question: str, allow_llm: bool, out_of_resin: bool
) -> Iterator[str]:
    """The /ask/stream body. A fresh RAG answer is paid for even if the client hangs up
    before the `done` event: the LLM call already happened, so leaving early is not free."""
    pending = False
    try:
        for kind, payload in engine.ask_stream(
            question, allow_llm=allow_llm, out_of_resin=out_of_resin
        ):
            if kind == "meta":
                pending = payload["route"] == "rag"
            if kind == "done":
                pending = False
                _spend(limits, cid, payload["route"], payload["trace"])
                payload = {**payload, "quota": _quota(limits, cid)}
            yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    except Exception:
        # Headers are already sent, so report a generic error event instead of a traceback.
        log.exception("stream failed")
        yield f"event: error\ndata: {json.dumps({'detail': ERROR_DETAIL})}\n\n"
    finally:
        if pending:
            _spend(limits, cid, "rag", {})


def _spend(limits: Limits, cid: str, route: str, trace: dict) -> None:
    # Only fresh AI-written answers cost anything; exact answers, cache hits and refusals
    # are free for the player and for the budget.
    if route == "rag" and trace.get("cache") != "hit":
        limits.spend_llm()
        limits.spend_resin(cid)


def _quota(limits: Limits, cid: str) -> dict:
    snap = limits.snapshot()
    return {
        "resin": limits.resin(cid),
        "world": {
            "left": max(0, snap["llm_per_day"] - snap["llm_used_today"]),
            "per_day": snap["llm_per_day"],
            "resets_in_s": snap["llm_resets_in_s"],
        },
    }


def create_app(
    engine: Engine,
    limits: Limits | None = None,
    meta: dict | None = None,
    trusted_hops: int = 0,
    cors: list[str] | None = None,
    frame_ancestors: str = "'none'",
) -> FastAPI:
    limits = limits or Limits()
    app = FastAPI(
        title="Irminsul",
        version="1.0.0a0",
        description="Genshin Impact answers from official, version-tagged data.",
    )
    if cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors,
            allow_methods=["GET", "POST"],
            allow_headers=["content-type"],
        )
    app.add_middleware(BodyLimit, max_bytes=MAX_BODY_BYTES)
    app.add_middleware(SecurityHeaders, frame_ancestors=frame_ancestors)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Starlette re-raises after this, so the traceback still reaches the server log;
        # clients only ever see a generic message.
        return JSONResponse(status_code=500, content={"detail": ERROR_DETAIL})

    def cid_of(request: Request) -> str:
        return client_id(request, trusted_hops)

    @app.get("/health")
    def health() -> dict:
        # Provider names and whether a key is set; never the key, its env name or base URL.
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

    @app.get("/quota")
    def quota(request: Request) -> dict:
        """The caller's Resin (AI answers they can still ask for) and the shared daily budget."""
        return _quota(limits, cid_of(request))

    @app.post("/ask/stream")
    def ask_stream(body: AskRequest, request: Request):
        """Server-sent events: `meta` (route + candidate citations), `delta` (text chunks),
        `done` (final route, the citations actually used, trace, and the caller's quota)."""
        cid = cid_of(request)
        if reason := limits.allow(cid):
            return JSONResponse(status_code=429, content={"detail": reason})
        return StreamingResponse(
            sse_events(
                engine,
                limits,
                cid,
                body.question,
                allow_llm=limits.llm_budget_left(),
                out_of_resin=not limits.has_resin(cid),
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/ask", response_model=AskResponse)
    def ask(body: AskRequest, request: Request):
        cid = cid_of(request)
        if reason := limits.allow(cid):
            return JSONResponse(status_code=429, content={"detail": reason})
        # Once the daily LLM budget or the player's Resin is spent, free routes still work
        # and LLM questions get a polite reply instead.
        allow_llm = limits.llm_budget_left()
        answer = engine.ask(
            body.question, allow_llm=allow_llm, out_of_resin=not limits.has_resin(cid)
        )
        _spend(limits, cid, answer.route, answer.trace)
        return AskResponse(
            answer=answer.text,
            route=answer.route,
            citations=[CitationOut(**asdict(c)) for c in answer.citations],
            trace=answer.trace,
        )

    return app
