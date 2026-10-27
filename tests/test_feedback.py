"""Feedback: strict validation, the personal-data refusal, the rate limit, and the flush to
the private dataset (with a fake HF API: no network)."""

import json
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from irminsul.api.feedback import (
    LIMIT_REPLY,
    PERSONAL_DATA_REPLY,
    FeedbackStore,
    add_feedback,
    hour_stamp,
)
from irminsul.api.limits import Window

ANSWER = {
    "rating": "down",
    "reason": "wrong_info",
    "comment": "The ER number looks off",
    "question": "How much Energy Recharge does Raiden need?",
    "route": "rag",
    "doc_ids": ["character/raiden-shogun#overview", "kqm/raiden#er"],
    "game_version": "71F2",
}


class FakeHfApi:
    def __init__(self, fail: bool = False):
        self.fail, self.uploads = fail, []

    def upload_file(self, *, path_or_fileobj, path_in_repo, repo_id, repo_type, commit_message):
        if self.fail:
            raise RuntimeError("hub is down")
        self.uploads.append(
            {
                "path": path_in_repo,
                "repo_id": repo_id,
                "repo_type": repo_type,
                "lines": [json.loads(x) for x in path_or_fileobj.read().decode().splitlines()],
            }
        )


def client(store=None, per_hour=10):
    store = store or FeedbackStore()
    app = FastAPI()
    add_feedback(app, store, per_hour=per_hour)
    return TestClient(app), store


def test_answer_feedback_is_stored_without_ip_and_with_an_hourly_timestamp():
    c, store = client()
    r = c.post("/feedback", json=ANSWER)
    assert r.status_code == 200 and r.json() == {"ok": True}
    [rec] = store.pending()
    assert rec["rating"] == "down" and rec["reason"] == "wrong_info" and rec["route"] == "rag"
    assert rec["doc_ids"] == ANSWER["doc_ids"] and rec["kind"] == "answer"
    assert rec["at"].endswith(":00:00+00:00")
    assert "testclient" not in json.dumps(rec)  # the TestClient's address is never kept
    assert set(rec) <= {"at", "kind", "rating", "reason", "comment", "question", "route",
                        "doc_ids", "game_version"}  # fmt: skip


def test_validation_is_strict():
    c, store = client()
    bad = [
        {**ANSWER, "comment": "x" * 501},
        {**ANSWER, "rating": "meh"},
        {**ANSWER, "reason": "too spicy"},
        {**ANSWER, "route": "<script>"},
        {**ANSWER, "doc_ids": ["ok"] * 13},
        {**ANSWER, "doc_ids": ["has space"]},
        {**ANSWER, "question": "q" * 601},
        {**ANSWER, "ip": "1.2.3.4"},  # unknown fields are refused, not ignored
        {**ANSWER, "rating": "up"},  # a reason only goes with a thumbs-down
        {"rating": "none", "question": "hi"},  # answer feedback needs a rating
        {"kind": "general", "rating": "none"},  # general feedback needs a comment
        {"kind": "general", "comment": "nice", "question": "smuggled"},
    ]
    for body in bad:
        assert c.post("/feedback", json=body).status_code == 422, body
    assert store.pending() == []
    assert c.post("/feedback", json={"kind": "general", "comment": "Love it"}).status_code == 200
    assert c.post("/feedback", json={"rating": "up", "route": "exact"}).status_code == 200


def test_personal_data_is_refused_and_nothing_is_stored():
    c, store = client()
    for body in (
        {**ANSWER, "comment": "email me at traveler@example.com"},
        {**ANSWER, "question": "my phone is 555 123 4567, call me"},
        {"kind": "general", "comment": "I live at 12 Baker Street"},
    ):
        r = c.post("/feedback", json=body)
        assert r.status_code == 400 and r.json()["detail"] == PERSONAL_DATA_REPLY
    assert store.pending() == []


def test_rate_limit_per_client():
    c, store = client(per_hour=3)
    codes = [c.post("/feedback", json={"rating": "up"}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert c.post("/feedback", json={"rating": "up"}).json()["detail"] == LIMIT_REPLY
    assert len(store.pending()) == 3


def test_window_slides():
    w = Window(limit=2, seconds=3600)
    assert w.allow("a", now=0) and w.allow("a", now=10) and not w.allow("a", now=20)
    assert w.allow("b", now=20)  # per client
    assert w.allow("a", now=3601)  # the first one has left the window


def test_flush_uploads_one_dated_jsonl_file_to_the_private_dataset():
    api = FakeHfApi()
    c, store = client(FeedbackStore(api, repo="someone/feedback"))
    for _ in range(3):
        c.post("/feedback", json={"rating": "up", "route": "exact"})
    assert store.flush(datetime(2026, 10, 26, 14, 37, tzinfo=UTC)) == 3
    [up] = api.uploads
    assert up["repo_id"] == "someone/feedback" and up["repo_type"] == "dataset"
    assert up["path"].startswith("feedback/2026-10-26/1400-") and up["path"].endswith(".jsonl")
    assert len(up["lines"]) == 3 and all(x["rating"] == "up" for x in up["lines"])
    assert store.pending() == [] and store.flush() == 0  # nothing left, nothing uploaded


def test_failed_flush_keeps_records_for_the_next_try():
    api = FakeHfApi(fail=True)
    store = FeedbackStore(api)
    store.add({"kind": "answer", "rating": "up", "route": "exact", "at": hour_stamp()})
    assert store.flush() == 0 and len(store.pending()) == 1
    api.fail = False
    assert store.flush() == 1 and store.pending() == []


def test_shutdown_flushes_and_memory_only_without_a_token(monkeypatch):
    api = FakeHfApi()
    store = FeedbackStore(api, flush_every_s=3600)
    with client(store)[0] as c:  # the context manager runs the app's startup and shutdown
        c.post("/feedback", json={"rating": "up", "route": "exact"})
        assert api.uploads == []
    assert len(api.uploads) == 1 and store.pending() == []

    monkeypatch.delenv("HF_FEEDBACK_TOKEN", raising=False)
    monkeypatch.setenv("HF_TOKEN", "read-only-token-must-not-be-used")
    memory = FeedbackStore.from_env()
    assert not memory.uploading and memory.flush() == 0
    for _ in range(250):
        memory.add({"kind": "general", "rating": "none", "comment": "hi", "at": hour_stamp()})
    assert len(memory.pending()) == 200  # a small ring buffer, never unbounded


def test_summary_counts_the_last_seven_days_per_route():
    store = FeedbackStore()
    now = 1_000_000_000.0
    store.add({"kind": "answer", "rating": "up", "route": "exact"}, now=now - 8 * 86400)
    store.add({"kind": "answer", "rating": "up", "route": "exact"}, now=now - 3600)
    store.add({"kind": "answer", "rating": "down", "route": "rag"}, now=now - 60)
    store.add({"kind": "general", "rating": "none", "comment": "hi"}, now=now)
    s = store.summary(now=now)
    assert s["routes"] == {"exact": {"up": 1, "down": 0}, "rag": {"up": 0, "down": 1}}
    assert s["up"] == 1 and s["down"] == 1 and s["days"] == 7
    c, _ = client()
    assert c.get("/api/feedback-summary").json()["up"] == 0
