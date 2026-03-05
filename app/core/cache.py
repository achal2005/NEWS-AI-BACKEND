"""
Simple TTL-based in-memory cache for API responses.

No Redis dependency needed — works great for single-instance deployments
(Render free tier). For multi-instance, swap for Redis.
"""

import time
import logging
from typing import Any, Optional
from threading import Lock

logger = logging.getLogger(__name__)


class TTLCache:
    """Thread-safe in-memory cache with TTL expiry."""

    def __init__(self):
        self._store: dict[str, tuple[Any, float]] = {}  # key -> (value, expires_at)
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        """Get value if key exists and hasn't expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.time() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        """Store value with TTL in seconds (default: 5 minutes)."""
        with self._lock:
            self._store[key] = (value, time.time() + ttl)

    def invalidate(self, prefix: str = "") -> int:
        """Invalidate all keys matching prefix. Returns count of removed keys."""
        with self._lock:
            if not prefix:
                count = len(self._store)
                self._store.clear()
                return count
            keys_to_remove = [k for k in self._store if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._store[k]
            return len(keys_to_remove)

    @property
    def size(self) -> int:
        return len(self._store)


# Singleton caches
article_list_cache = TTLCache()
summary_cache = TTLCache()
