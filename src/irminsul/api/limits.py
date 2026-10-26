"""Abuse and cost limits for a free public endpoint.

Irminsul runs on free LLM tiers, so AI-written answers are rationed fairly:
- personal allowance: each player banks up to `allowance_cap` AI answers, refilling one at a
  time (a game-style stamina bar). Only fresh AI-written answers use it; exact game-data
  answers, cache hits and refusals are free, so nobody is ever fully locked out.
- shared pool: the daily AI budget (`llm_per_day`) refills steadily through the day instead
  of resetting at midnight, so players in every time zone get a share and early risers can't
  drain it. It can bank a small burst (`pool_cap`) for busy moments.
- per client: a short-window limit (burst) and a generous daily request cap (abuse only).
All in memory: a single small Space instance needs nothing more, and a restart only resets
counters (which errs on the generous side, never on the costly side for long).
"""

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Limits:
    per_minute: int = 6
    per_day: int = 200  # all requests, free ones included; stops scripted abuse
    llm_per_day: int = 500  # all players combined; keep below the providers' free tiers
    allowance_cap: int = 20  # AI answers a player can bank
    allowance_regen_s: int = 30 * 60  # +1 every 30 minutes
    pool_cap: int = 0  # shared-pool burst; 0 = an eighth of a day's budget

    _recent: dict[str, deque] = field(default_factory=lambda: defaultdict(deque))
    _daily: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _allowance: dict[str, tuple[float, float]] = field(default_factory=dict)  # (amount, at)
    _pool: tuple[float, float] | None = None  # (amount, at)
    _llm_used: int = 0  # today's count, for /health only
    _day: str = ""

    def __post_init__(self) -> None:
        if self.pool_cap <= 0:
            self.pool_cap = max(1, self.llm_per_day // 8)

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

    # Refilling buckets

    @staticmethod
    def _level(state: tuple[float, float] | None, cap: int, regen_s: float, now: float) -> float:
        amount, at = state if state is not None else (float(cap), now)
        return min(float(cap), amount + (now - at) / regen_s)

    @staticmethod
    def _view(amount: float, cap: int, regen_s: float) -> dict:
        full = amount >= cap
        return {
            "current": math.floor(amount),
            "cap": cap,
            "regen_s": round(regen_s, 1),
            "next_in_s": 0 if full else math.ceil((1 - amount % 1) * regen_s),
            "full_in_s": 0 if full else math.ceil((cap - amount) * regen_s),
        }

    # Personal allowance

    def has_allowance(self, client: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        state = self._allowance.get(client)
        return self._level(state, self.allowance_cap, self.allowance_regen_s, now) >= 1

    def spend_allowance(self, client: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        state = self._allowance.get(client)
        level = self._level(state, self.allowance_cap, self.allowance_regen_s, now)
        self._allowance[client] = (max(0.0, level - 1), now)

    def allowance(self, client: str, now: float | None = None) -> dict:
        """What the player's counter shows: current/cap, next point and full refill, seconds."""
        now = time.time() if now is None else now
        state = self._allowance.get(client)
        level = self._level(state, self.allowance_cap, self.allowance_regen_s, now)
        return self._view(level, self.allowance_cap, self.allowance_regen_s)

    # Shared pool

    @property
    def _pool_regen_s(self) -> float:
        return 86400 / self.llm_per_day

    def llm_budget_left(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return self._level(self._pool, self.pool_cap, self._pool_regen_s, now) >= 1

    def spend_llm(self, now: float | None = None) -> None:
        self._roll_day()
        now = time.time() if now is None else now
        level = self._level(self._pool, self.pool_cap, self._pool_regen_s, now)
        self._pool = (max(0.0, level - 1), now)
        self._llm_used += 1

    def pool(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        level = self._level(self._pool, self.pool_cap, self._pool_regen_s, now)
        return {**self._view(level, self.pool_cap, self._pool_regen_s), "per_day": self.llm_per_day}

    def snapshot(self) -> dict:
        self._roll_day()
        return {
            "llm_used_today": self._llm_used,
            "llm_per_day": self.llm_per_day,
            "clients_today": len(self._daily),
            "allowance_cap": self.allowance_cap,
            "allowance_regen_s": self.allowance_regen_s,
            "pool_cap": self.pool_cap,
        }
