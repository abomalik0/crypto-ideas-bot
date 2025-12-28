"""
engine_metrics.py

✅ الهدف: تجميع منطق حسابات السوق (Market Metrics) في ملف مستقل.
ملاحظة: حالياً هذا الملف غير مربوط بالشغل الفعلي إلا عندما نبدأ مرحلة الربط لاحقاً.
"""

from __future__ import annotations

import time

import config
from engine_data_sources import fetch_price_data


def build_symbol_metrics(
    price: float,
    change_pct: float,
    high: float,
    low: float,
) -> dict:
    if price > 0 and high >= low:
        range_pct = ((high - low) / price) * 100.0
    else:
        range_pct = 0.0

    volatility_raw = abs(change_pct) * 1.5 + range_pct
    volatility_score = max(0.0, min(100.0, volatility_raw))

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


def compute_market_metrics() -> dict | None:
    data = fetch_price_data("BTCUSDT")
    if not data:
        return None

    return build_symbol_metrics(
        data["price"],
        data["change_pct"],
        data["high"],
        data["low"],
    )


def get_market_metrics_cached() -> dict | None:
    now = time.time()
    data = config.MARKET_METRICS_CACHE.get("data")
    ts = config.MARKET_METRICS_CACHE.get("time", 0.0)

    if data and (now - ts) <= config.MARKET_TTL_SECONDS:
        return data

    data = compute_market_metrics()
    if data:
        config.MARKET_METRICS_CACHE["data"] = data
        config.MARKET_METRICS_CACHE["time"] = now
    return data
