"""
engine_metrics.py

✅ الهدف: حساب Metrics السوق (Range/Volatility/Labels) بشكل مستقل + كاش TTL.
- يعتمد على engine_data_sources.fetch_price_data
- يستخدم engine_cache (TTLCache) لتقليل الضغط على الـ APIs

ملاحظة:
- لا يوجد أي تعامل مع توكنات هنا.
- الملف جاهز للربط لاحقاً داخل analysis_engine.py بدون كسر الشغل الحالي.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import config
from engine_cache import cache_get, cache_set
from engine_data_sources import fetch_price_data


def build_symbol_metrics(
    price: float,
    change_pct: float,
    high: float,
    low: float,
) -> Dict[str, Any]:
    """يبني Metrics موحدة من بيانات السعر."""
    if price > 0 and high >= low:
        range_pct = ((high - low) / price) * 100.0
    else:
        range_pct = 0.0

    # تقلب تقديري (0..100)
    volatility_raw = abs(change_pct) * 1.5 + range_pct
    volatility_score = max(0.0, min(100.0, volatility_raw))

    # Label للاتجاه
    if change_pct >= 3:
        strength_label = "صعود قوى وزخم واضح فى الحركة."
    elif change_pct >= 1:
        strength_label = "اتجاه صاعد جيد مع حركة إيجابية."
    elif change_pct <= -3:
        strength_label = "هبوط حاد وزخم بيعى واضح."
    elif change_pct <= -1:
        strength_label = "اتجاه هابط متوسط مع ضغط بيعى."
    else:
        strength_label = "حركة جانبية أو تغير بسيط فى السعر."

    # Pulse للسيولة بشكل استدلالي
    if volatility_score >= 70:
        if change_pct >= 2:
            liquidity_pulse = "اندفاع شرائى قوى وسيولة مرتفعة."
        elif change_pct <= -2:
            liquidity_pulse = "اندفاع بيعى قوى وسيولة مرتفعة."
        else:
            liquidity_pulse = "تقلبات مرتفعة مع سيولة نشطة."
    elif change_pct >= 2 and range_pct > 4:
        liquidity_pulse = "زخم صاعد جيد مع اتساع النطاق."
    elif change_pct <= -2 and range_pct > 4:
        liquidity_pulse = "خروج سيولة واضح مع هبوط ملحوظ."
    else:
        liquidity_pulse = "يوجد بعض الضغوط البيعية لكن بدون ذعر كبير."

    return {
        "price": price,
        "change_pct": change_pct,
        "high": high,
        "low": low,
        "range_pct": range_pct,
        "volatility_score": volatility_score,
        "strength_label": strength_label,
        "liquidity_pulse": liquidity_pulse,
    }


def compute_market_metrics(user_symbol: str = "BTCUSDT") -> Optional[Dict[str, Any]]:
    """يجلب بيانات السعر ويبني metrics."""
    data = fetch_price_data(user_symbol)
    if not data:
        return None

    try:
        price = float(data.get("price") or 0.0)
        change_pct = float(data.get("change_pct") or 0.0)
        high = float(data.get("high") or price)
        low = float(data.get("low") or price)
    except Exception:
        return None

    metrics = build_symbol_metrics(
        price=price,
        change_pct=change_pct,
        high=high,
        low=low,
    )

    # إضافات مفيدة للتشخيص
    metrics["symbol"] = data.get("symbol", user_symbol)
    metrics["exchange"] = data.get("exchange")
    metrics["volume"] = data.get("volume")
    return metrics


def get_market_metrics_cached(
    user_symbol: str = "BTCUSDT",
    ttl_seconds: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    نفس compute_market_metrics لكن بكاش TTL (افتراضي: MARKET_TTL_SECONDS من config).
    """
    ttl = int(ttl_seconds or getattr(config, "MARKET_TTL_SECONDS", 20))
    key = f"metrics:{(user_symbol or 'BTCUSDT').upper()}"

    cached = cache_get(key)
    if cached:
        return cached

    data = compute_market_metrics(user_symbol)
    if data:
        cache_set(key, data, ttl=ttl)
    return data
