"""
engine_cache.py

✅ TTL Cache خفيف وسريع ومناسب لـ Koyeb free plan.
- Thread-safe
- Supports per-key TTL
- Max size protection
- Periodic cleanup
- Stats for debugging

ملاحظة: ملف مستقل لتقليل حجم الملفات الضخمة وتسهيل تتبع الأخطاء.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass
class _Entry:
    value: Any
    expires_at: float
    created_at: float


class TTLCache:
    def __init__(self, max_items: int = 256, default_ttl: int = 120) -> None:
        self.max_items = int(max_items)
        self.default_ttl = int(default_ttl)
        self._lock = threading.Lock()
        self._data: Dict[str, _Entry] = {}

        # stats
        self._hits = 0
        self._misses = 0
        self._sets = 0
        self._evicts = 0
        self._cleans = 0

    def _now(self) -> float:
        return time.monotonic()

    def _cleanup_locked(self) -> None:
        now = self._now()
        expired = [k for k, e in self._data.items() if e.expires_at <= now]
        for k in expired:
            self._data.pop(k, None)
        if expired:
            self._cleans += 1

    def _evict_if_needed_locked(self) -> None:
        # Evict oldest entries if max exceeded
        if len(self._data) <= self.max_items:
            return

        # Sort by created_at (oldest first)
        items = sorted(self._data.items(), key=lambda kv: kv[1].created_at)
        overflow = len(self._data) - self.max_items
        for i in range(max(0, overflow)):
            k, _ = items[i]
            if k in self._data:
                self._data.pop(k, None)
                self._evicts += 1

    def get(self, key: str, default: Any = None) -> Any:
        k = str(key)
        with self._lock:
            self._cleanup_locked()
            e = self._data.get(k)
            if not e:
                self._misses += 1
                return default

            if e.expires_at <= self._now():
                # expired
                self._data.pop(k, None)
                self._misses += 1
                return default

            self._hits += 1
            return e.value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        k = str(key)
        ttl_s = self.default_ttl if ttl is None else int(ttl)
        now = self._now()
        expires = now + max(1, ttl_s)

        with self._lock:
            self._data[k] = _Entry(value=value, expires_at=expires, created_at=now)
            self._sets += 1
            self._cleanup_locked()
            self._evict_if_needed_locked()

    def delete(self, key: str) -> bool:
        k = str(key)
        with self._lock:
            existed = k in self._data
            self._data.pop(k, None)
            return existed

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def size(self) -> int:
        with self._lock:
            self._cleanup_locked()
            return len(self._data)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            self._cleanup_locked()
            return {
                "size": len(self._data),
                "max_items": self.max_items,
                "default_ttl": self.default_ttl,
                "hits": self._hits,
                "misses": self._misses,
                "sets": self._sets,
                "evicts": self._evicts,
                "cleans": self._cleans,
                "hit_rate": round(self._hits / max(1, (self._hits + self._misses)), 4),
            }


# Global cache instance (اختياري للاستخدام السريع)
GLOBAL_CACHE = TTLCache(max_items=256, default_ttl=120)


def cache_get(key: str, default: Any = None) -> Any:
    return GLOBAL_CACHE.get(key, default=default)


def cache_set(key: str, value: Any, ttl: Optional[int] = None) -> None:
    GLOBAL_CACHE.set(key, value=value, ttl=ttl)


def cache_stats() -> Dict[str, Any]:
    return GLOBAL_CACHE.stats()
