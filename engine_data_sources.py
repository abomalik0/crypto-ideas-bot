"""
engine_data_sources.py

هدف الملف: كل شغل الشبكة (Binance/Kucoin/requests) يكون هنا لاحقًا.
مرحلة 1: هيكل فقط بدون ربط فعلي (لعدم كسر الشغل الحالي).
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def normalize_symbol(symbol: str) -> str:
    """
    Normalize بسيط كبداية (هيستبدل بالمنطق الحقيقي لاحقاً عند النقل).
    """
    symbol = (symbol or "").upper().strip()
    if not symbol:
        return "BTCUSDT"
    if not symbol.endswith("USDT") and len(symbol) <= 6:
        symbol += "USDT"
    return symbol


def fetch_price_data(symbol: str) -> Optional[Dict[str, Any]]:
    """
    Placeholder: سيتم نقل المنطق الحقيقي من analysis_engine لاحقاً.
    """
    _ = normalize_symbol(symbol)
    return None
