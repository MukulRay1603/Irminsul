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
    # with no trusted proxy, a forged X-Forwarded-For is ignored: still the same client
    spoofed = c.post("/ask", json=q, headers={"x-forwarded-for": "203.0.113.9"})
    assert spoofed.status_code == 429


def test_rate_limit_per_client_behind_one_proxy():
    engine = Engine(store(), FakeIndex(), FakeLLM())
    c = TestClient(create_app(engine, Limits(per_minute=1), trusted_hops=1))
    q = {"question": "What are Raiden Shogun's base stats?"}
    assert c.post("/ask", json=q, headers={"x-forwarded-for": "198.51.100.1"}).status_code == 200
    # the proxy appends the real address; whatever the client wrote before it is ignored
    forged = {"x-forwarded-for": "203.0.113.9, 198.51.100.1"}
    assert c.post("/ask", json=q, headers=forged).status_code == 429
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


def test_allowance_is_spent_only_by_ai_answers():
    from irminsul.engine.engine import ALLOWANCE_REPLY

    c = client(Limits(allowance_cap=1))
    stats = {"question": "What are Raiden Shogun's base stats?"}
    assert c.post("/ask", json=stats).json()["route"] == "exact"
    assert c.get("/quota").json()["personal"]["current"] == 1  # game-data answers are free
    rag = c.post("/ask", json={"question": "How much ER does Raiden need?"}).json()
    assert rag["route"] == "rag"
    quota = c.get("/quota").json()
    assert quota["personal"]["current"] == 0 and 0 < quota["personal"]["next_in_s"] <= 1800
    empty = c.post("/ask", json={"question": "Is Raiden good in Hyperbloom?"}).json()
    assert empty["route"] == "no_allowance" and empty["answer"] == ALLOWANCE_REPLY
    assert c.post("/ask", json=stats).json()["route"] == "exact"  # still free when empty


def test_allowance_refills_one_at_a_time():
    limits = Limits(allowance_cap=3, allowance_regen_s=480)
    for _ in range(3):
        limits.spend_allowance("p", now=0)
    view = limits.allowance("p", now=0)
    assert view["current"] == 0 and view["next_in_s"] == 480 and view["full_in_s"] == 1440
    assert limits.allowance("p", now=500)["current"] == 1
    assert limits.allowance("p", now=5000)["current"] == 3
    assert limits.allowance("someone-new", now=0)["current"] == 3


def test_shared_pool_refills_through_the_day_not_at_midnight():
    limits = Limits(llm_per_day=240)  # one answer every 6 minutes, burst of 30
    assert limits.pool(now=0)["cap"] == 30
    for _ in range(30):
        assert limits.llm_budget_left(now=0)
        limits.spend_llm(now=0)
    assert not limits.llm_budget_left(now=0)
    assert limits.pool(now=0)["next_in_s"] == 360
    assert limits.llm_budget_left(now=360)  # the next answer frees up 6 minutes later


def test_stream_done_event_carries_quota():
    r = client().post("/ask/stream", json={"question": "What are Raiden Shogun's base stats?"})
    assert '"quota"' in r.text and '"personal"' in r.text and '"pool"' in r.text
