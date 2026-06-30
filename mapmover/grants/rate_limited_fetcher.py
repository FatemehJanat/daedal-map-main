"""
Shared rate-limited HTTP fetcher for no-key, undocumented-limit APIs.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests


class RateLimitedFetcher:
    def __init__(self, min_interval: float = 1.0, max_retries: int = 5, timeout: int = 60, stats_path: Path | None = None):
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self.stats_path = Path(stats_path) if stats_path else None
        self._last_request_at = 0.0
        self.stats = {
            "total_requests": 0,
            "total_429s": 0,
            "total_errors": 0,
            "max_latency_s": 0.0,
            "min_latency_s": None,
            "latency_sum_s": 0.0,
            "events": [],
        }

    def _wait_for_slot(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.min_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _record(self, status_code: int, latency_s: float, note: str | None = None) -> None:
        self.stats["total_requests"] += 1
        self.stats["latency_sum_s"] += latency_s
        self.stats["max_latency_s"] = max(self.stats["max_latency_s"], latency_s)
        self.stats["min_latency_s"] = (
            latency_s
            if self.stats["min_latency_s"] is None
            else min(self.stats["min_latency_s"], latency_s)
        )
        if status_code != 200:
            self.stats["events"].append(
                {
                    "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "status_code": status_code,
                    "latency_s": round(latency_s, 3),
                    "note": note,
                }
            )

    def _request(self, method: str, url: str, **kwargs):
        last_exception = None
        for attempt in range(1, self.max_retries + 1):
            self._wait_for_slot()
            start = time.monotonic()
            try:
                response = requests.request(method, url, timeout=self.timeout, **kwargs)
            except Exception as exc:
                self._last_request_at = time.monotonic()
                latency = time.monotonic() - start
                self._record(0, latency, note=f"exception: {exc}")
                last_exception = exc
                time.sleep(self.min_interval * attempt)
                continue

            self._last_request_at = time.monotonic()
            latency = time.monotonic() - start

            if response.status_code == 429:
                self.stats["total_429s"] += 1
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else self.min_interval * (2 ** attempt)
                self._record(429, latency, note=f"retry_after={retry_after}")
                time.sleep(wait)
                continue

            if response.status_code >= 500:
                self.stats["total_errors"] += 1
                self._record(response.status_code, latency)
                time.sleep(self.min_interval * attempt)
                continue

            self._record(response.status_code, latency)
            return response

        self.stats["total_errors"] += 1
        raise RuntimeError(f"Failed {method} {url} after {self.max_retries} attempts: {last_exception}")

    def get(self, url: str, **kwargs):
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self._request("POST", url, **kwargs)

    def write_stats(self) -> None:
        if not self.stats_path:
            return
        report = dict(self.stats)
        count = report["total_requests"]
        report["avg_latency_s"] = round(report["latency_sum_s"] / count, 3) if count else None
        self.stats_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.stats_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
