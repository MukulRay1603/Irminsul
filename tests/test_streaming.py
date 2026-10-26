"""Streaming: SSE parsing, router failover rules, engine events and the /ask/stream endpoint."""

import json
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient
from test_engine import FakeIndex, store

from irminsul.api.app import create_app
from irminsul.api.limits import Limits
from irminsul.engine.engine import BUSY_REPLY, Engine
from irminsul.engine.llm import AllProvidersBusy, Completion, Provider, Router, _sse_deltas


def sse(*deltas: str) -> list[str]:
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': d}}]})}" for d in deltas]
    return [": keep-alive", *lines, "data: [DONE]"]


def test_sse_parser_reads_deltas_and_stops_at_done():
    out = list(_sse_deltas(iter(sse("Rai", "den") + ['data: {"choices": []}'])))
    assert [d for d, _ in out] == ["Rai", "den"]  # nothing after [DONE] is read


class FakeStreamResp:
    def __init__(self, status=200, lines=(), fail_after=None):
        self.status_code, self._lines, self._fail_after = status, list(lines), fail_after

    def raise_for_status(self):
        pass

    def iter_lines(self):
        for i, line in enumerate(self._lines):
            if self._fail_after is not None and i >= self._fail_after:
                raise httpx.ReadError("connection dropped")
            yield line


def patch_stream(monkeypatch, responses: dict[str, FakeStreamResp]):
    calls = []

    @contextmanager
    def fake_stream(method, url, **kwargs):
        calls.append(url)
        yield responses[url.split("/")[2]]

    monkeypatch.setattr("irminsul.engine.llm.httpx.stream", fake_stream)
    return calls


def providers(*names):
    return [Provider(n, f"https://{n}", "m", f"{n.upper()}_KEY", 10) for n in names]


def test_router_stream_fails_over_before_first_token(monkeypatch):
    monkeypatch.setenv("A_KEY", "x")
    monkeypatch.setenv("B_KEY", "y")
    calls = patch_stream(
        monkeypatch, {"a": FakeStreamResp(429), "b": FakeStreamResp(lines=sse("Hi", " [1]"))}
    )
    router = Router(providers("a", "b"))
    items = list(router.stream([]))
    assert items[:2] == ["Hi", " [1]"]
    assert isinstance(items[-1], Completion) and items[-1].provider == "b"
    assert items[-1].text == "Hi [1]" and len(calls) == 2


def test_router_stream_does_not_switch_provider_mid_answer(monkeypatch):
    monkeypatch.setenv("A_KEY", "x")
    monkeypatch.setenv("B_KEY", "y")
    calls = patch_stream(
        monkeypatch,
        {
            "a": FakeStreamResp(lines=sse("Partial", " answer"), fail_after=2),
            "b": FakeStreamResp(lines=sse("Other")),
        },
    )
    router = Router(providers("a", "b"))
    items = list(router.stream([]))
    assert items[-1].text == "Partial" and items[-1].provider == "a"
    assert len(calls) == 1 and "interrupted" in router.attempts[-1]


def test_router_stream_raises_when_nothing_available(monkeypatch):
    monkeypatch.delenv("A_KEY", raising=False)
    with pytest.raises(AllProvidersBusy):
        list(Router(providers("a")).stream([]))


class FakeStreamLLM:
    def __init__(self, chunks=("ER 200-220%", " [1]"), busy=False):
        self.chunks, self.busy = chunks, busy

    def stream(self, messages, max_tokens=1024):
        if self.busy:
            raise AllProvidersBusy()
        yield from self.chunks
        yield Completion("".join(self.chunks), "fake", "fake-model", 10, 5)


def test_engine_streams_rag_and_reports_used_citations():
    engine = Engine(store(), FakeIndex(), FakeStreamLLM())
    events = list(engine.ask_stream("How much ER does Raiden need in National?"))
    kinds = [k for k, _ in events]
    assert kinds == ["meta", "delta", "delta", "done"]
    done = events[-1][1]
    assert done["route"] == "rag" and [c["n"] for c in done["citations"]] == [1]
    assert done["trace"]["provider"] == "fake"
    # the streamed answer is cached like a normal one
    again = engine.ask("How much ER does Raiden need in National?")
    assert again.trace.get("cache") == "hit"


def test_engine_streams_free_routes_as_one_delta():
    events = list(Engine(store()).ask_stream("What are Raiden Shogun's base stats?"))
    assert [k for k, _ in events] == ["meta", "delta", "done"]
    assert events[0][1]["route"] == "exact" and "337" in events[1][1]["text"]


def test_engine_stream_busy_and_budget_spent():
    busy = list(
        Engine(store(), FakeIndex(), FakeStreamLLM(busy=True)).ask_stream(
            "How much ER does Raiden need?"
        )
    )
    assert busy[-1][1]["route"] == "busy" and busy[-2][1]["text"] == BUSY_REPLY
    spent = list(
        Engine(store(), FakeIndex(), FakeStreamLLM()).ask_stream(
            "How much ER does Raiden need?", allow_llm=False
        )
    )
    assert spent[-1][1]["route"] == "busy"


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_ask_stream_endpoint():
    engine = Engine(store(), FakeIndex(), FakeStreamLLM())
    limits = Limits(llm_per_day=5)
    client = TestClient(create_app(engine, limits))
    r = client.post("/ask/stream", json={"question": "How much ER does Raiden need?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    assert [k for k, _ in events] == ["meta", "delta", "delta", "done"]
    assert "".join(p["text"] for k, p in events if k == "delta") == "ER 200-220% [1]"
    assert limits.snapshot()["llm_used_today"] == 1
