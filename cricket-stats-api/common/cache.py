import asyncio
import time
import hashlib
import json
from functools import wraps
from typing import Any, Optional


class TTLCache:
    """Simple in-process TTL cache. Thread-safe enough for single-worker async."""

    def __init__(self, maxsize: int = 1000, ttl: int = 300):
        self._store: dict[str, tuple[Any, float]] = {}
        self._maxsize = maxsize
        self._ttl = ttl

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        if len(self._store) >= self._maxsize:
            # evict oldest quarter
            cutoff = time.time()
            expired = [k for k, (_, e) in self._store.items() if e < cutoff]
            for k in expired[:max(1, len(expired))]:
                del self._store[k]
        self._store[key] = (value, time.time() + (ttl or self._ttl))

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


def make_cache_key(*args, **kwargs) -> str:
    raw = json.dumps({"a": args, "k": kwargs}, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()


def cached(cache: TTLCache, ttl: Optional[int] = None):
    """Async-compatible decorator that caches by function args."""
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            key = f"{fn.__qualname__}:{make_cache_key(*args, **kwargs)}"
            hit = cache.get(key)
            if hit is not None:
                return hit
            result = await fn(*args, **kwargs)
            cache.set(key, result, ttl)
            return result
        return wrapper
    return decorator
