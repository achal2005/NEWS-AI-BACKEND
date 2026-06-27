"""
Simple TTL-based in-memory cache for API responses.

No Redis dependency needed — works great for single-instance deployments
(Render free tier). For multi-instance, swap for Redis.

Memory-safe: enforces max entry count and periodic expired-key eviction.
"""

import time
import logging
from typing import Any, Optional
from threading import Lock

logger = logging.getLogger(__name__)

# Maximum entries per cache instance — prevents unbounded memory growth
DEFAULT_MAX_ENTRIES = 100


class TTLCache:
    """Thread-safe in-memory cache with TTL expiry and max size limit."""

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES):
        self._store: dict[str, tuple[Any, float]] = {}  # key -> (value, expires_at)
        self._lock = Lock()
        self._max_entries = max_entries

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
            # Evict expired entries first to reclaim memory
            if len(self._store) >= self._max_entries:
                self._evict_expired()

            # If still at capacity after evicting expired, drop oldest entries
            if len(self._store) >= self._max_entries:
                # Remove the 25% oldest entries (by expiry time)
                to_remove = max(1, self._max_entries // 4)
                sorted_keys = sorted(
                    self._store.keys(),
                    key=lambda k: self._store[k][1]  # sort by expires_at
                )
                for k in sorted_keys[:to_remove]:
                    del self._store[k]

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

    def _evict_expired(self) -> int:
        """Remove all expired entries. Must be called under lock. Returns count removed."""
        now = time.time()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
        return len(expired)

    @property
    def size(self) -> int:
        return len(self._store)


# Singleton cache with conservative limits for Render free tier (512MB).
# Article summaries are cached in the DB (ArticleSummary table), not here.
article_list_cache = TTLCache(max_entries=50)   # ~50 cached pages max
