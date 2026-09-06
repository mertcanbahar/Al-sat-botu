"""Simple disk-backed cache for HTTP responses.

Avoids unnecessary API calls (and rate-limit errors) by persisting
responses to JSON files under a cache directory, keyed by a hash of the
request parameters and expiring after a configurable TTL.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .. import config


class DiskCache:
    def __init__(self, cache_dir: Path | None = None, ttl_seconds: int | None = None) -> None:
        self.cache_dir = Path(cache_dir or config.CACHE_DIR)
        self.ttl_seconds = ttl_seconds if ttl_seconds is not None else config.CACHE_TTL_SECONDS
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, namespace: str, key: dict[str, Any]) -> Path:
        payload = json.dumps({"namespace": namespace, "key": key}, sort_keys=True)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{namespace}_{digest}.json"

    def get(self, namespace: str, key: dict[str, Any]) -> Any | None:
        path = self._path_for(namespace, key)
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > self.ttl_seconds:
            return None
        try:
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)["data"]
        except (json.JSONDecodeError, KeyError, OSError):
            return None

    def set(self, namespace: str, key: dict[str, Any], data: Any) -> None:
        path = self._path_for(namespace, key)
        with path.open("w", encoding="utf-8") as fh:
            json.dump({"cached_at": time.time(), "data": data}, fh)
