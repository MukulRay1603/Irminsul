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

import json
import os
import time
import tomllib
from collections.abc import Iterator
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
    def complete(self, messages: list[dict], max_tokens: int = 1024) -> Completion: ...


@dataclass
class Provider:
    name: str
    base_url: str
    model: str
    api_key_env: str
    daily_requests: int
    enabled: bool = True
    extra: dict = field(default_factory=dict)  # provider-specific request params
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
            self.enabled
            and bool(self.api_key)
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

    def complete(self, messages: list[dict], max_tokens: int = 1024) -> Completion:
        # 1024: reasoning models (gpt-oss) need headroom beyond the visible answer.
        self.attempts = []
        for p in self.providers:
            if not p.available(time.monotonic()):
                reason = "disabled" if not p.enabled else "no key, cap or cooldown"
                self.attempts.append({"provider": p.name, "skipped": reason})
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
                        **p.extra,
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

    def stream(self, messages: list[dict], max_tokens: int = 1024) -> Iterator[str | Completion]:
        """Yield text deltas as they arrive, then one final `Completion`.

        Failover only happens before the first token: once text has reached the user,
        switching providers would produce a mixed answer, so a mid-stream failure just ends it
        (the final Completion is marked `interrupted` in the attempts).
        """
        self.attempts = []
        for p in self.providers:
            if not p.available(time.monotonic()):
                reason = "disabled" if not p.enabled else "no key, cap or cooldown"
                self.attempts.append({"provider": p.name, "skipped": reason})
                continue
            start, parts, usage = time.perf_counter(), [], {}
            retry = interrupted = False
            try:
                with httpx.stream(
                    "POST",
                    f"{p.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {p.api_key}"},
                    json={
                        "model": p.model,
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": self.temperature,
                        "stream": True,
                        **p.extra,
                    },
                    timeout=self.timeout_s,
                ) as resp:
                    p.used_today += 1
                    if resp.status_code == 429 or resp.status_code >= 500:
                        p.cooldown_until = time.monotonic() + self.cooldown_s
                        self.attempts.append({"provider": p.name, "error": resp.status_code})
                        retry = True
                    else:
                        resp.raise_for_status()
                        for delta, chunk_usage in _sse_deltas(resp.iter_lines()):
                            usage = chunk_usage or usage
                            if delta:
                                parts.append(delta)
                                yield delta
            except httpx.TransportError as e:
                if not parts:
                    p.cooldown_until = time.monotonic() + self.cooldown_s
                    self.attempts.append({"provider": p.name, "error": type(e).__name__})
                    continue
                self.attempts.append({"provider": p.name, "interrupted": type(e).__name__})
                interrupted = True
            if retry:
                continue
            if not interrupted:
                self.attempts.append({"provider": p.name, "ok": True})
            yield Completion(
                text="".join(parts),
                provider=p.name,
                model=p.model,
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                latency_ms=(time.perf_counter() - start) * 1000,
            )
            return
        raise AllProvidersBusy("no LLM provider is available right now")


def _sse_deltas(lines: Iterator[str]) -> Iterator[tuple[str, dict]]:
    """Parse OpenAI-style server-sent events into (text delta, usage) pairs."""
    for line in lines:
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        chunk = json.loads(data)
        delta = "".join(
            (choice.get("delta") or {}).get("content") or ""
            for choice in chunk.get("choices") or []
        )
        yield delta, chunk.get("usage") or {}
