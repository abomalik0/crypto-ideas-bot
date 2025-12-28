"""
engine_smart_classifier.py

✅ الهدف: تصنيف مستوى التنبيه (Alert Level) بناءً على:
- metrics (change/range/volatility)
- pulse (speed/accel/regime/conf/percentiles)
- risk (score/level)
- events (active_count/flags)

ملاحظة: هذا الملف جاهز للربط التدريجي لاحقاً بدون كسر الشغل الحالي.
"""

from __future__ import annotations


def _clamp(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def _score01(x: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return _clamp((x - lo) / (hi - lo), 0.0, 1.0)


def classify_alert_level(pulse: dict, metrics: dict, risk: dict, events: dict) -> dict:
    """
    يرجّع:
    - level: low/medium/high/critical
    - shock_score: 0..100
    - trend_bias: bull/bear/neutral
    - reasons: list[str]
    """
    change = float(metrics.get("change_pct", 0.0))
    range_pct = float(metrics.get("range_pct", 0.0))
    vol = float(metrics.get("volatility_score", 0.0))

    speed = float(pulse.get("speed_index", 0.0))
    accel = float(pulse.get("accel_index", 0.0))
    conf = float(pulse.get("direction_confidence", 0.0))
    regime = pulse.get("regime")

    # percentiles (لو موجودة من pulse history)
    vol_pct = float(pulse.get("vol_percentile", 0.0))
    rng_pct = float(pulse.get("range_percentile", 0.0))

    risk_score = float(risk.get("score", 0.0))
    risk_level = risk.get("level", "low")

    active_count = int(events.get("active_count", 0))

    reasons: list[str] = []

    # -------- Shock components (0..1) --------
    # تغير السعر (abs)
    change_s = _score01(abs(change), 0.3, 3.5)
    # التقلب
    vol_s = _score01(vol, 10.0, 70.0)
    # مدى الحركة
    range_s = _score01(range_pct, 0.8, 8.0)
    # السرعة والتسارع
    speed_s = _score01(speed, 5.0, 45.0)
    accel_s = _score01(abs(accel), 2.0, 25.0)
    # مخاطرة عامة
    risk_s = _score01(risk_score, 5.0, 60.0)
    # الأحداث المؤسسية
    events_s = _score01(float(active_count), 0.0, 4.0)

    # percentiles (لو موجودة تزيد دقة التقييم بدل thresholds ثابتة)
    # لو مفيش تاريخ، هتكون 0 وده طبيعي.
    vol_pct_s = _score01(vol_pct, 50.0, 95.0)
    rng_pct_s = _score01(rng_pct, 50.0, 95.0)

    # -------- Weighted shock score --------
    # توزيع الأوزان عشان shock يبقى واقعي ويفيد SmartAlert
    shock = (
        0.18 * change_s +
        0.18 * vol_s +
        0.14 * range_s +
        0.14 * speed_s +
        0.08 * accel_s +
        0.14 * risk_s +
        0.10 * events_s +
        0.02 * vol_pct_s +
        0.02 * rng_pct_s
    ) * 100.0

    shock = _clamp(shock, 0.0, 100.0)

    # -------- Trend bias --------
    if change > 0.2 and conf >= 45:
        trend_bias = "bull"
        reasons.append(f"اتجاه صاعد بثقة {conf:.0f}%")
    elif change < -0.2 and conf >= 45:
        trend_bias = "bear"
        reasons.append(f"اتجاه هابط بثقة {conf:.0f}%")
    else:
        trend_bias = "neutral"

    # -------- Level thresholds --------
    # ندي قوة إضافية لو regime = explosion أو events كتير أو risk high
    boost = 0.0
    if regime == "explosion":
        boost += 8.0
        reasons.append("Regime: انفجار تقلبات")
    elif regime == "expansion":
        boost += 3.0

    if active_count >= 2:
        boost += 6.0
        reasons.append(f"إشارات مؤسسية: {active_count}")

    if risk_level == "high":
        boost += 6.0
        reasons.append("مخاطر مرتفعة")
    elif risk_level == "medium":
        boost += 2.5

    shock_adj = _clamp(shock + boost, 0.0, 100.0)

    if shock_adj >= 75:
        level = "critical"
    elif shock_adj >= 55:
        level = "high"
    elif shock_adj >= 35:
        level = "medium"
    else:
        level = "low"

    # Reasons إضافية للتشخيص
    if abs(change) >= 2.0:
        reasons.append(f"تغير قوي: {change:+.2f}%")
    if vol >= 60:
        reasons.append(f"تقلب مرتفع: {vol:.1f}")
    if speed >= 30:
        reasons.append(f"سرعة حركة عالية: {speed:.1f}")
    if abs(accel) >= 10:
        reasons.append(f"تسارع ملحوظ: {accel:+.1f}")

    return {
        "level": level,
        "shock_score": round(shock_adj, 2),
        "trend_bias": trend_bias,
        "boost": round(boost, 2),
        "reasons": reasons[:8],  # نحددها عشان ما تطولش
    }
