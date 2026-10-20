"""HTTP for job sources: identifiable User-Agent, spacing between requests, ETag cache, backoff, offline mode.

Every response body is cached in var/cache/http (gitignored). ``offline`` reads only the cache (no network):
that is how ``encaixe bench`` and the tests replay recorded responses.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

import httpx

from app import clock
from app.config import RULES, get_settings

log = logging.getLogger(__name__)


class SourceUnavailable(Exception):
    pass


class HttpClient:
    def __init__(
        self,
        source: str,
        *,
        offline: bool = False,
        cache_dir: Path | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ) -> None:  # type: ignore[no-untyped-def]
        self.source = source
        self.rules = RULES.ingest.sources[source]
        self.offline = offline
        self.cache_dir = (cache_dir or get_settings().http_cache_dir) / source
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = httpx.Client(
            headers={"User-Agent": RULES.ingest.user_agent, "Accept": "application/json"},
            timeout=RULES.ingest.timeout_s,
            transport=transport,
            follow_redirects=True,
        )
        self._sleep = sleep
        self._last = 0.0
        self.requests = 0

    def _path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha256(url.encode("utf-8")).hexdigest()[:24] + ".json")

    def cached(self, url: str) -> dict | None:
        p = self._path(url)
        if not p.is_file():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def store(self, url: str, body: object, etag: str | None, status: int = 200) -> None:
        self._path(url).write_text(
            json.dumps(
                {"url": url, "etag": etag, "status": status, "fetched_at": clock.now().isoformat(), "body": body},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def get_json(self, url: str, extra_headers: dict[str, str] | None = None) -> object:
        entry = self.cached(url)
        if self.offline:
            if entry is None:
                raise SourceUnavailable(f"offline and not cached: {url}")
            return entry["body"]
        headers = dict(extra_headers or {})
        if entry and entry.get("etag"):
            headers["If-None-Match"] = entry["etag"]
        for attempt, wait in enumerate((0.0, *RULES.ingest.backoff_s)):
            if wait:
                self._sleep(wait)
            gap = self.rules.min_interval_s - (time.monotonic() - self._last)
            if gap > 0:
                self._sleep(gap)
            self._last = time.monotonic()
            self.requests += 1
            try:
                resp = self._client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                log.warning("%s %s: %s (attempt %d)", self.source, url, exc, attempt + 1)
                continue
            if resp.status_code == 304 and entry is not None:
                return entry["body"]
            if resp.status_code == 200:
                body = resp.json()
                self.store(url, body, resp.headers.get("ETag"))
                return body
            if resp.status_code in (429, 500, 502, 503, 504):
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    self._sleep(min(float(retry_after), 120.0))
                continue
            raise SourceUnavailable(f"{self.source} {url}: HTTP {resp.status_code}")
        raise SourceUnavailable(f"{self.source} {url}: gave up after retries")

    def close(self) -> None:
        self._client.close()
