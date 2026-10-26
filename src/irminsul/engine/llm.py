"""A small multi-provider LLM router with failover and per-provider budgets.

Every provider in `config/llm_providers.toml` speaks the OpenAI-compatible chat API, so one
client covers them all. The router:
- skips providers whose API key is not set (nothing runs until keys exist),
- enforces our own daily request cap per provider (kept below each free tier),
- on a rate limit (429) or server error, cools that provider down and tries the next one,
- reports which provider answered and the token usage, for tracing and cost tracking.
If every provider is unavailable, it raises `AllProvidersBusy`; the engine then returns a
polite "busy" answer instead of an error.
"""

import os
import time
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx

CONFIG = Path(__file__).resolve().parents[3] / "config" / "llm_providers.toml"


class AllProvidersBusy(RuntimeError):
    pass


@dataclass
class Completion:
    text: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0


class ChatModel(Protocol):
    def complete(self, messages: list[dict], max_tokens: int = 700) -> Completion: ...


@dataclass
class Provider:
    name: str
    base_url: str
    model: str
    api_key_env: str
    daily_requests: int
    used_today: int = 0
    day: str = ""
    cooldown_until: float = 0.0

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env)

    def available(self, now: float) -> bool:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if self.day != today:
            self.day, self.used_today = today, 0
        return (
            bool(self.api_key)
            and self.used_today < self.daily_requests
            and now >= self.cooldown_until
        )


@dataclass
class Router:
    providers: list[Provider]
    timeout_s: float = 30.0
    cooldown_s: float = 60.0
    temperature: float = 0.2
    attempts: list[dict] = field(default_factory=list)  # last call's attempts, for the trace

    @classmethod
    def from_config(cls, path: Path = CONFIG) -> "Router":
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return cls([Provider(**p) for p in data.get("provider", [])])

    def complete(self, messages: list[dict], max_tokens: int = 700) -> Completion:
        self.attempts = []
        for p in self.providers:
            if not p.available(time.monotonic()):
                self.attempts.append({"provider": p.name, "skipped": "no key, cap or cooldown"})
                continue
            start = time.perf_counter()
            try:
                resp = httpx.post(
                    f"{p.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {p.api_key}"},
                    json={
                        "model": p.model,
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": self.temperature,
                    },
                    timeout=self.timeout_s,
                )
            except httpx.TransportError as e:
                p.cooldown_until = time.monotonic() + self.cooldown_s
                self.attempts.append({"provider": p.name, "error": type(e).__name__})
                continue
            p.used_today += 1
            if resp.status_code == 429 or resp.status_code >= 500:
                p.cooldown_until = time.monotonic() + self.cooldown_s
                self.attempts.append({"provider": p.name, "error": resp.status_code})
                continue
            resp.raise_for_status()
            body = resp.json()
            usage = body.get("usage") or {}
            self.attempts.append({"provider": p.name, "ok": True})
            return Completion(
                text=body["choices"][0]["message"]["content"] or "",
                provider=p.name,
                model=p.model,
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                latency_ms=(time.perf_counter() - start) * 1000,
            )
        raise AllProvidersBusy("no LLM provider is available right now")
