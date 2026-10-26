"""POST /feedback: anonymous 👍/👎 on answers, plus a general "Send feedback" form.

Privacy first (see web/about.html):
- No IPs, client ids or cookies are stored. The client id is only used, in memory, for the
  rate limit. Timestamps are rounded down to the hour, and each flushed file is shuffled so
  the order of lines says nothing about who sent what when.
- A comment or question that looks like personal data (guards.has_personal_data) is refused
  with a friendly message and nothing is stored.
- Storage: records are buffered in memory and flushed every 15 minutes (and on shutdown) as
  a new dated JSONL file in a PRIVATE HF dataset, written with a dedicated write token
  (HF_FEEDBACK_TOKEN) scoped to that one dataset. The read-only HF_TOKEN is never used here.
  Without the token, feedback is kept in a small in-memory ring buffer only.

GET /api/feedback-summary gives 👍/👎 counts per route over the last 7 days (in memory, so a
restart starts it over) for the public results page.
"""

import asyncio
import io
import json
import logging
import os
import random
import secrets
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from irminsul.api.app import client_id
from irminsul.api.limits import Window
from irminsul.engine.guards import MAX_CHARS, has_personal_data

log = logging.getLogger("irminsul.feedback")

REPO = "MukulRay/irminsul-feedback"
TOKEN_ENV = "HF_FEEDBACK_TOKEN"
FLUSH_EVERY_S = 15 * 60
RING_SIZE = 200  # kept when there is no token: enough to look at in a debugger, no more
MAX_PENDING = 5000  # records waiting for a flush; a long outage drops the oldest
SUMMARY_DAYS = 7
PER_HOUR = 10

PERSONAL_DATA_REPLY = (
    "That looks like it has personal details in it (an email, phone number, address or "
    "similar). Please leave those out: feedback is anonymous. Nothing was saved."
)
LIMIT_REPLY = "Thanks for all the feedback! Please wait a little before sending more."

Reason = Literal["wrong_info", "missing_info", "hard_to_read", "not_answered"]
DocId = Annotated[str, StringConstraints(max_length=120, pattern=r"^[A-Za-z0-9/_#.:-]+$")]


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["answer", "general"] = "answer"
    rating: Literal["up", "down", "none"] = "none"
    reason: Reason | None = None
    comment: str | None = Field(default=None, max_length=500)
    # Answer feedback only, all from the client's `done` payload
    question: str | None = Field(default=None, max_length=MAX_CHARS)
    route: str | None = Field(default=None, max_length=32, pattern=r"^[a-z_]+$")
    doc_ids: list[DocId] = Field(default_factory=list, max_length=12)
    game_version: str | None = Field(default=None, max_length=16, pattern=r"^[0-9A-Za-z.]+$")

    @model_validator(mode="after")
    def _consistent(self) -> "FeedbackIn":
        if self.kind == "general":
            if self.question or self.route or self.doc_ids or self.game_version:
                raise ValueError("general feedback carries no answer details")
            if not self.comment:
                raise ValueError("general feedback needs a comment")
        elif self.rating == "none":
            raise ValueError("answer feedback needs a rating")
        if self.reason and self.rating != "down":
            raise ValueError("a reason goes with a thumbs-down")
        return self


def hour_stamp(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return now.replace(minute=0, second=0, microsecond=0).isoformat()


class FeedbackStore:
    """The buffer, the flush to the private dataset, and the 7-day counts.

    `api` is a huggingface_hub.HfApi (or a fake in tests); None means memory only.
    """

    def __init__(self, api=None, repo: str = REPO, flush_every_s: float = FLUSH_EVERY_S):
        self.api, self.repo, self.flush_every_s = api, repo, flush_every_s
        self._pending: deque[dict] = deque(maxlen=MAX_PENDING if api else RING_SIZE)
        self._counts: deque[tuple[float, str, str]] = deque(maxlen=20000)  # (at, route, rating)
        self._lock = threading.Lock()
        self._flush_lock = threading.Lock()  # one upload at a time
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @classmethod
    def from_env(cls) -> "FeedbackStore":
        token = os.environ.get(TOKEN_ENV, "").strip()
        if not token:
            log.info("%s is not set: feedback is kept in memory only", TOKEN_ENV)
            return cls()
        from huggingface_hub import HfApi

        return cls(HfApi(token=token), os.environ.get("IRMINSUL_FEEDBACK_REPO", REPO))

    @property
    def uploading(self) -> bool:
        return self.api is not None

    def add(self, record: dict, now: float | None = None) -> None:
        with self._lock:
            self._pending.append(record)
            if record["kind"] == "answer":
                route = record.get("route") or "unknown"
                self._counts.append((time.time() if now is None else now, route, record["rating"]))

    def pending(self) -> list[dict]:
        with self._lock:
            return list(self._pending)

    def flush(self, now: datetime | None = None) -> int:
        """Upload what is buffered as one new JSONL file; return how many records went up.

        On a failed upload the records go back in the buffer for the next try.
        """
        if not self.uploading:
            return 0
        with self._flush_lock:
            with self._lock:
                batch = list(self._pending)
                self._pending.clear()
            if not batch:
                return 0
            random.shuffle(batch)
            body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in batch)
            now = now or datetime.now(UTC)
            path = f"feedback/{now:%Y-%m-%d}/{now:%H}00-{secrets.token_hex(4)}.jsonl"
            try:
                self.api.upload_file(
                    path_or_fileobj=io.BytesIO(body.encode("utf-8")),
                    path_in_repo=path,
                    repo_id=self.repo,
                    repo_type="dataset",
                    commit_message=f"feedback: {len(batch)} record(s)",
                )
            except Exception:
                log.exception("feedback upload failed; keeping %d record(s) for later", len(batch))
                with self._lock:
                    self._pending.extendleft(reversed(batch))
                return 0
            return len(batch)

    def summary(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        cutoff = now - SUMMARY_DAYS * 86400
        routes: dict[str, dict[str, int]] = defaultdict(lambda: {"up": 0, "down": 0})
        with self._lock:
            while self._counts and self._counts[0][0] < cutoff:
                self._counts.popleft()
            for _, route, rating in self._counts:
                if rating in ("up", "down"):
                    routes[route][rating] += 1
        return {
            "days": SUMMARY_DAYS,
            "since": hour_stamp(datetime.fromtimestamp(cutoff, UTC)),
            "routes": dict(sorted(routes.items())),
            "up": sum(r["up"] for r in routes.values()),
            "down": sum(r["down"] for r in routes.values()),
        }

    # Background flushing

    def start(self) -> None:
        if not self.uploading or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="feedback-flush", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.flush_every_s):
            self.flush()

    def stop(self) -> None:
        """Stop the timer and flush whatever is left (called on shutdown)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self.flush()


def add_feedback(
    app: FastAPI,
    store: FeedbackStore | None = None,
    trusted_hops: int = 0,
    per_hour: int = PER_HOUR,
) -> FeedbackStore:
    store = store or FeedbackStore.from_env()
    window = Window(limit=per_hour, seconds=3600)

    # Flush on a timer while the app runs, and once more on shutdown.
    inner = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a):
        async with inner(a) as state:
            store.start()
            try:
                yield state
            finally:
                await asyncio.to_thread(store.stop)

    app.router.lifespan_context = lifespan

    @app.post("/feedback")
    def feedback(body: FeedbackIn, request: Request):
        """Anonymous feedback. Stores no IP or client id; refuses anything personal."""
        if not window.allow(client_id(request, trusted_hops)):
            return JSONResponse(status_code=429, content={"detail": LIMIT_REPLY})
        if any(t and has_personal_data(t) for t in (body.comment, body.question)):
            return JSONResponse(status_code=400, content={"detail": PERSONAL_DATA_REPLY})
        record = {"at": hour_stamp(), **body.model_dump(exclude_none=True)}
        if not record.get("doc_ids"):
            record.pop("doc_ids", None)
        store.add(record)
        return {"ok": True}

    @app.get("/api/feedback-summary")
    def feedback_summary() -> dict:
        return store.summary()

    return store
