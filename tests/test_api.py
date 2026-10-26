"""API tests with the in-memory test engine (no data files, no models, no network)."""

from fastapi.testclient import TestClient
from test_engine import FakeIndex, FakeLLM, store

from irminsul.api.app import create_app
from irminsul.api.limits import Limits
from irminsul.engine.engine import BUSY_REPLY, Engine


def client(limits=None, llm=None):
    engine = Engine(store(), FakeIndex(), llm if llm is not None else FakeLLM())
    return TestClient(create_app(engine, limits or Limits(), {"game_version": "71F2"}))


def test_health_reports_corpus_and_no_secrets():
    body = client().get("/health").json()
    assert body["status"] == "ok" and body["corpus"]["game_version"] == "71F2"
    assert body["entities"] > 0 and body["index_chunks"] == 0  # FakeIndex has no chunks attr
    assert "api_key" not in str(body).lower()


def test_ask_exact_answer_with_citation():
    r = client().post("/ask", json={"question": "What are Raiden Shogun's base stats?"})
    body = r.json()
    assert r.status_code == 200 and body["route"] == "exact" and "337" in body["answer"]
    assert body["citations"][0]["doc_id"] == "character/raiden-shogun#overview"


def test_ask_refuses_leaks_without_llm():
    llm = FakeLLM()
    body = client(llm=llm).post("/ask", json={"question": "What are the 7.3 leaks?"}).json()
    assert body["route"] == "refuse_leak" and llm.calls == 0


def test_validation_rejects_empty_and_huge_questions():
    c = client()
    assert c.post("/ask", json={"question": ""}).status_code == 422
    assert c.post("/ask", json={"question": "a" * 5000}).status_code == 422


def test_per_client_rate_limit():
    c = client(Limits(per_minute=2, per_day=100))
    q = {"question": "What are Raiden Shogun's base stats?"}
    assert c.post("/ask", json=q).status_code == 200
    assert c.post("/ask", json=q).status_code == 200
    r = c.post("/ask", json=q)
    assert r.status_code == 429 and "wait" in r.json()["detail"]
    # a different client (behind the proxy) is not affected
    other = c.post("/ask", json=q, headers={"x-forwarded-for": "203.0.113.9"})
    assert other.status_code == 200


def test_daily_llm_budget_keeps_free_routes_working():
    llm = FakeLLM()
    c = client(Limits(llm_per_day=1), llm=llm)
    first = c.post("/ask", json={"question": "How much ER does Raiden need in National?"})
    assert first.json()["route"] == "rag"
    second = c.post("/ask", json={"question": "Is Raiden still good in National teams?"})
    assert second.json()["route"] == "busy" and second.json()["answer"] == BUSY_REPLY
    exact = c.post("/ask", json={"question": "What are Raiden Shogun's base stats?"})
    assert exact.json()["route"] == "exact" and llm.calls == 1
