"""Abuse and cost limits for a free public endpoint.

- per client: a short-window limit (burst) and a daily limit
- global: a daily budget of LLM-backed answers; once spent, only free routes (exact answers,
  refusals, cache hits) keep working and LLM questions get a polite "busy" reply
All in memory: a single small Space instance needs nothing more, and a restart only resets
counters (which errs on the generous side, never on the costly side for long).
"""

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Limits:
    per_minute: int = 6
    per_day: int = 60
    llm_per_day: int = 1500  # all users combined; keep below the providers' free tiers

    _recent: dict[str, deque] = field(default_factory=lambda: defaultdict(deque))
    _daily: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _llm_used: int = 0
    _day: str = ""

    def _roll_day(self) -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if today != self._day:
            self._day, self._daily, self._llm_used = today, defaultdict(int), 0

    def allow(self, client: str, now: float | None = None) -> str | None:
        """Record a request; return a reason string if it must be rejected."""
        self._roll_day()
        now = time.monotonic() if now is None else now
        window = self._recent[client]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.per_minute:
            return "Too many questions in a short time. Please wait a minute."
        if self._daily[client] >= self.per_day:
            return "You've reached today's question limit. Please come back tomorrow!"
        window.append(now)
        self._daily[client] += 1
        return None

    def llm_budget_left(self) -> bool:
        self._roll_day()
        return self._llm_used < self.llm_per_day

    def spend_llm(self) -> None:
        self._roll_day()
        self._llm_used += 1

    def snapshot(self) -> dict:
        self._roll_day()
        return {
            "llm_used_today": self._llm_used,
            "llm_per_day": self.llm_per_day,
            "clients_today": len(self._daily),
        }
