"""Abuse and cost limits for a free public endpoint.

- per client: a short-window limit (burst) and a daily request cap (abuse only; generous)
- per client: Resin, modelled on Genshin's Original Resin. Each AI-written answer costs 1,
  it refills 1 point at a time up to a cap, and anything answered without the LLM (exact
  game data, cache hits, refusals) is free. Players see the counter and the refill timer.
- global: a daily budget of LLM-backed answers (the "ley line" budget); once spent, only free
  routes keep working and LLM questions get a polite "busy" reply. Resets at 00:00 UTC.
All in memory: a single small Space instance needs nothing more, and a restart only resets
counters (which errs on the generous side, never on the costly side for long). Per-client
entries that carry no information (an expired burst window, a full Resin bar) are pruned, so
memory follows the clients active in the last day, not every client ever seen.
"""

import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta


@dataclass
class Limits:
    per_minute: int = 6
    per_day: int = 200  # all requests, free ones included; stops scripted abuse
    llm_per_day: int = 500  # all users combined; keep below the providers' free tiers
    resin_cap: int = 30  # AI-written answers a player can bank
    resin_regen_s: int = 24 * 60  # +1 Resin every 24 minutes, so a full refill takes 12 hours
    prune_every: int = 1000  # requests between sweeps of stale per-client entries

    _recent: dict[str, deque] = field(default_factory=lambda: defaultdict(deque))
    _daily: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _resin: dict[str, tuple[float, float]] = field(default_factory=dict)  # (amount, at)
    _llm_used: int = 0
    _day: str = ""
    _since_prune: int = 0
    # FastAPI runs sync endpoints in a thread pool, so counters are updated under a lock.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _roll_day(self) -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if today != self._day:
            self._day, self._daily, self._llm_used = today, defaultdict(int), 0

    def allow(self, client: str, now: float | None = None) -> str | None:
        """Record a request; return a reason string if it must be rejected."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._roll_day()
            self._since_prune += 1
            if self._since_prune >= self.prune_every:
                self._prune(now, time.time())
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

    def _prune(self, now: float, wall: float) -> None:
        """Drop entries that no longer change any decision. `_daily` resets with the day."""
        self._since_prune = 0
        for client, window in list(self._recent.items()):
            if not window or now - window[-1] > 60:
                del self._recent[client]
        for client in list(self._resin):
            if self._resin_now(client, wall) >= self.resin_cap:
                del self._resin[client]  # a full bar is the same as never having asked

    # Resin: a regenerating allowance per player

    def _resin_now(self, client: str, now: float) -> float:
        amount, at = self._resin.get(client, (float(self.resin_cap), now))
        return min(float(self.resin_cap), amount + (now - at) / self.resin_regen_s)

    def has_resin(self, client: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        return self._resin_now(client, now) >= 1

    def spend_resin(self, client: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            self._resin[client] = (max(0.0, self._resin_now(client, now) - 1), now)

    def resin(self, client: str, now: float | None = None) -> dict:
        """What the player's counter shows: current/cap, next point and full refill in seconds."""
        now = time.time() if now is None else now
        amount = self._resin_now(client, now)
        full = amount >= self.resin_cap
        next_in = 0 if full else math.ceil((1 - amount % 1) * self.resin_regen_s)
        return {
            "current": math.floor(amount),
            "cap": self.resin_cap,
            "regen_s": self.resin_regen_s,
            "next_in_s": next_in,
            "full_in_s": 0 if full else math.ceil((self.resin_cap - amount) * self.resin_regen_s),
        }

    # Global daily budget

    def llm_budget_left(self) -> bool:
        self._roll_day()
        return self._llm_used < self.llm_per_day

    def spend_llm(self) -> None:
        with self._lock:
            self._roll_day()
            self._llm_used += 1

    def resets_in_s(self) -> int:
        now = datetime.now(UTC)
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return math.ceil((midnight - now).total_seconds())

    def snapshot(self) -> dict:
        self._roll_day()
        return {
            "llm_used_today": self._llm_used,
            "llm_per_day": self.llm_per_day,
            "llm_resets_in_s": self.resets_in_s(),
            "clients_today": len(self._daily),
            "resin_cap": self.resin_cap,
            "resin_regen_s": self.resin_regen_s,
        }
