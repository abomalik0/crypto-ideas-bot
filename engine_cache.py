"""
engine_cache.py

هدف الملف: كاش TTL بسيط in-memory.
مرحلة 1: إضافة هيكل فقط (مش مربوط بالشغل القديم) للحفاظ على الاستقرار 100%.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional, Tuple


class TTLCache:
    """
    كاش بسيط جداً (مناسب لـ Koyeb free وعدد مستخدمين قليل).
    """

    def __init__(self) -> None:
        self._store: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        item = self._store.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at and time.time() > expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: float = 0.0) -> None:
        expires_at = time.time() + ttl_seconds if ttl_seconds and ttl_seconds > 0 else 0.0
        self._store[key] = (expires_at, value)

    def get_or_set(self, key: str, ttl_seconds: float, factory: Callable[[], Any]) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = factory()
        self.set(key, value, ttl_seconds=ttl_seconds)
        return value

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


# كاشات جاهزة للاستخدام لاحقًا (مش مستخدمة الآن)
PRICE_CACHE = TTLCache()
METRICS_CACHE = TTLCache()
TEXT_CACHE = TTLCache()
