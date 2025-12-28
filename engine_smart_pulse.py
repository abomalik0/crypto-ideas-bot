"""
engine_smart_pulse.py

✅ الهدف: عزل Smart Pulse Engine (السرعة/التسارع/الثقة/النظام السوقي)
في ملف مستقل عشان تتبع الأخطاء يكون أسرع والتعديل يبقى أسهل.

ملاحظة: الملف ده جاهز للنقل التدريجي من analysis_engine.py بدون كسر الشغل الحالي.
"""

from __future__ import annotations

import time

import config


def _compute_volatility_regime(volatility_score: float, range_pct: float) -> str:
    if volatility_score < 20 and range_pct < 3:
        return "calm"
    if volatility_score < 40 and range_pct < 5:
        return "normal"
    if volatility_score < 70 and range_pct < 8:
        return "expansion"
    return "explosion"


def update_market_pulse(metrics: dict) -> dict:
    """
    تحديث نبض السوق وتخزين آخر القراءات فى PULSE_HISTORY داخل config
    مع حساب إحصائيات تاريخية (متوسط + انحراف معيارى + percentiles)
    لاستخدامها فى بناء قراءات ديناميكية أدق.
    """
    price = float(metrics["price"])
    change = float(metrics["change_pct"])
    range_pct = float(metrics["range_pct"])
    vol = float(metrics["volatility_score"])

    regime = _compute_volatility_regime(vol, range_pct)

    # -------- تهيئة / استخدام تاريخ النبض --------
    history = getattr(config, "PULSE_HISTORY", None)
    if history is None:
        from collections import deque
        maxlen = getattr(config, "PULSE_HISTORY_MAXLEN", 120)
        history = deque(maxlen=maxlen)
        config.PULSE_HISTORY = history  # type: ignore[assignment]

    prev_entry = history[-1] if len(history) > 0 else None
    prev_regime = prev_entry.get("regime") if isinstance(prev_entry, dict) else None

    now = time.time()
    entry = {
        "time": now,
        "price": price,
        "change_pct": change,
        "volatility_score": vol,
        "range_pct": range_pct,
        "regime": regime,
    }
    history.append(entry)

    hist_list = list(history)
    n = len(hist_list)

    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    def _std(values: list[float], m: float) -> float:
        if not values:
            return 0.0
        var = sum((v - m) ** 2 for v in values) / max(1, len(values) - 1)
        return var ** 0.5

    # -------- سرعة الحركة & التسارع مثل الإصدار القديم --------
    if n >= 2:
        diffs = [
            abs(hist_list[i]["change_pct"] - hist_list[i - 1]["change_pct"])
            for i in range(1, n)
        ]
        avg_diff = _mean(diffs)
    else:
        avg_diff = 0.0

    if n >= 5:
        mid = max(2, n // 2)
        early_diffs = [
            abs(hist_list[i]["change_pct"] - hist_list[i - 1]["change_pct"])
            for i in range(1, mid)
        ]
        late_diffs = [
            abs(hist_list[i]["change_pct"] - hist_list[i - 1]["change_pct"])
            for i in range(mid, n)
        ]
        early_avg = _mean(early_diffs)
        late_avg = _mean(late_diffs)
        accel = late_avg - early_avg
    else:
        accel = 0.0

    # -------- ثقة الاتجاه من التاريخ القريب --------
    if n >= 3:
        recent = hist_list[-6:] if n >= 6 else hist_list
        same_sign_count = 0
        total = len(recent)
        for e in recent:
            c = e["change_pct"]
            if change > 0 and c > 0:
                same_sign_count += 1
            elif change < 0 and c < 0:
                same_sign_count += 1
        direction_conf = (same_sign_count / total) * 100.0 if total else 0.0
    else:
        direction_conf = 0.0

    # -------- baseline ديناميكى (متوسط + std + percentiles) --------
    if n >= 10:
        changes = [float(e["change_pct"]) for e in hist_list]
        vols = [float(e["volatility_score"]) for e in hist_list]
        ranges = [float(e["range_pct"]) for e in hist_list]

        mean_change = _mean(changes)
        std_change = _std(changes, mean_change)

        mean_vol = _mean(vols)
        std_vol = _std(vols, mean_vol)

        mean_range = _mean(ranges)
        std_range = _std(ranges, mean_range)

        sorted_vols = sorted(vols)
        rank = sum(1 for v in sorted_vols if v <= vol)
        vol_percentile = (rank / len(sorted_vols)) * 100.0 if sorted_vols else 0.0

        sorted_ranges = sorted(ranges)
        rank_r = sum(1 for v in sorted_ranges if v <= range_pct)
        range_percentile = (
            (rank_r / len(sorted_ranges)) * 100.0 if sorted_ranges else 0.0
        )
    else:
        mean_change = std_change = 0.0
        mean_vol = std_vol = 0.0
        mean_range = std_range = 0.0
        vol_percentile = range_percentile = 0.0

    speed_index = max(0.0, min(100.0, avg_diff * 8.0))
    accel_index = max(-100.0, min(100.0, accel * 10.0))

    pulse = {
        "time": now,
        "price": price,
        "change_pct": change,
        "volatility_score": vol,
        "range_pct": range_pct,
        "regime": regime,
        "prev_regime": prev_regime,
        "speed_index": speed_index,
        "accel_index": accel_index,
        "direction_confidence": direction_conf,
        "history_len": n,
        "mean_change": mean_change,
        "std_change": std_change,
        "mean_vol": mean_vol,
        "std_vol": std_vol,
        "mean_range": mean_range,
        "std_range": std_range,
        "vol_percentile": vol_percentile,
        "range_percentile": range_percentile,
    }

    return pulse
