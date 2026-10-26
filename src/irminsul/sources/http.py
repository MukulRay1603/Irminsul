"""A polite HTTP client: identifies itself, rate-limits, retries, optionally caches."""

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "irminsul-corpus/1.0 (+https://github.com/MukulRay1603/Irminsul)"
RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    pass


class PoliteClient:
    def __init__(
        self,
        delay_s: float = 0.35,
        retries: int = 4,
        cache_dir: Path | None = None,
        headers: dict[str, str] | None = None,
        timeout_s: float = 20.0,
    ) -> None:
        self.delay_s = delay_s
        self.retries = retries
        self.cache_dir = cache_dir
        self._last = 0.0
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, **(headers or {})},
            timeout=timeout_s,
            follow_redirects=True,
        )

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        key = url + ("?" + json.dumps(params, sort_keys=True) if params else "")
        return self._request_json("GET", url, key, params=params)

    def post_json(self, url: str, body: Any) -> Any:
        key = "POST " + url + " " + json.dumps(body, sort_keys=True)
        return self._request_json("POST", url, key, json=body)

    def _request_json(self, method: str, url: str, key: str, **kwargs: Any) -> Any:
        cached = self._cache_path(key)
        if cached and cached.exists():
            return json.loads(cached.read_text(encoding="utf-8"))

        for attempt in range(self.retries + 1):
            self._wait()
            try:
                resp = self._client.request(method, url, **kwargs)
            except httpx.TransportError as e:
                err: str = f"transport error: {e}"
            else:
                if resp.status_code == 200:
                    data = resp.json()
                    if cached:
                        cached.parent.mkdir(parents=True, exist_ok=True)
                        cached.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                    return data
                if resp.status_code not in RETRY_STATUS:
                    raise FetchError(f"HTTP {resp.status_code} for {url}")
                err = f"HTTP {resp.status_code}"
            backoff = min(60.0, 2.0 ** (attempt + 1))
            log.warning(
                "%s for %s, retry %d/%d in %.0fs", err, url, attempt + 1, self.retries, backoff
            )
            time.sleep(backoff)
        raise FetchError(f"gave up on {url} after {self.retries} retries")

    def close(self) -> None:
        self._client.close()

    def _wait(self) -> None:
        gap = time.monotonic() - self._last
        if gap < self.delay_s:
            time.sleep(self.delay_s - gap)
        self._last = time.monotonic()

    def _cache_path(self, key: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")
