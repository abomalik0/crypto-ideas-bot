"""
engine_reports.py

✅ الهدف: تجميع منطق تنسيق/عرض التقارير والرسائل في ملف مستقل.
ده بيخلي تعديل الرسائل أسهل وأسرع بدل ما تفضل جوه ملف analysis_engine.py الضخم.

ملاحظة: هذا الملف جاهز للربط التدريجي لاحقاً بدون كسر الشغل الحالي.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def format_number(x: Any, digits: int = 2) -> str:
    try:
        if x is None:
            return "-"
        return f"{float(x):.{digits}f}"
    except Exception:
        return str(x)


def format_pct(x: Any, digits: int = 2, signed: bool = True) -> str:
    try:
        if x is None:
            return "-"
        v = float(x)
        if signed:
            return f"{v:+.{digits}f}%"
        return f"{v:.{digits}f}%"
    except Exception:
        return str(x)


def _risk_level_ar(level: str) -> str:
    if level == "low":
        return "منخفض"
    if level == "medium":
        return "متوسط"
    if level == "high":
        return "مرتفع"
    return str(level)


def _alert_level_ar(level: str) -> str:
    if level == "low":
        return "هادئ"
    if level == "medium":
        return "متوسط"
    if level == "high":
        return "قوي"
    if level == "critical":
        return "خطير جدًا"
    return str(level)


def build_compact_snapshot_text(snapshot: Dict[str, Any]) -> str:
    """
    تقرير مختصر جدًا (مفيد للتنبيهات السريعة).
    """
    symbol = snapshot.get("symbol", "BTCUSDT")
    metrics = snapshot.get("metrics") or {}
    risk = snapshot.get("risk") or {}
    pulse = snapshot.get("pulse") or {}
    alert = snapshot.get("alert") or {}
    zones = snapshot.get("zones") or {}

    price = metrics.get("price")
    change = metrics.get("change_pct")
    rng = metrics.get("range_pct")
    vol = metrics.get("volatility_score")

    risk_level = _risk_level_ar(risk.get("level", "low"))
    risk_score = risk.get("score")

    level = alert.get("level", "low")
    shock = alert.get("shock_score", 0.0)
    trend_bias = alert.get("trend_bias", "neutral")

    speed = pulse.get("speed_index", 0.0)
    accel = pulse.get("accel_index", 0.0)
    conf = pulse.get("direction_confidence", 0.0)

    support = zones.get("support")
    resistance = zones.get("resistance")

    bias_txt = "محايد"
    if trend_bias == "bull":
        bias_txt = "صاعد"
    elif trend_bias == "bear":
        bias_txt = "هابط"

    msg = f"""
📌 <b>Snapshot سريع</b> — <b>{symbol}</b>

السعر: <b>{format_number(price, 2)}</b>
التغير 24h: <b>{format_pct(change, 2, signed=True)}</b>
النطاق: <b>{format_number(rng, 2)}%</b> — التقلب: <b>{format_number(vol, 1)}</b>/100

مستوى التنبيه: <b>{_alert_level_ar(level)}</b> (Shock: <b>{format_number(shock, 1)}</b>/100) — اتجاه: <b>{bias_txt}</b>
المخاطر: <b>{risk_level}</b> (Score ≈ <b>{format_number(risk_score, 1)}</b>)

السرعة: <b>{format_number(speed, 1)}</b> — التسارع: <b>{format_number(accel, 1)}</b> — ثقة الاتجاه: <b>{format_number(conf, 0)}%</b>

الدعم/المقاومة: <b>{format_number(support, 2)}</b> / <b>{format_number(resistance, 2)}</b>
""".strip()

    return msg


def build_detailed_snapshot_text(snapshot: Dict[str, Any]) -> str:
    """
    تقرير مفصل (مفيد للداشبورد أو أمر /smart).
    """
    symbol = snapshot.get("symbol", "BTCUSDT")
    price_data = snapshot.get("price_data") or {}
    metrics = snapshot.get("metrics") or {}
    risk = snapshot.get("risk") or {}
    pulse = snapshot.get("pulse") or {}
    events = snapshot.get("events") or {}
    alert = snapshot.get("alert") or {}
    zones = snapshot.get("zones") or {}

    price = metrics.get("price")
    change = metrics.get("change_pct")
    high = price_data.get("high")
    low = price_data.get("low")
    rng = metrics.get("range_pct")
    vol = metrics.get("volatility_score")

    regime = pulse.get("regime")
    prev_regime = pulse.get("prev_regime")
    speed = pulse.get("speed_index", 0.0)
    accel = pulse.get("accel_index", 0.0)
    conf = pulse.get("direction_confidence", 0.0)

    risk_level = _risk_level_ar(risk.get("level", "low"))
    risk_score = risk.get("score")

    level = alert.get("level", "low")
    shock = alert.get("shock_score", 0.0)
    boost = alert.get("boost", 0.0)
    reasons = alert.get("reasons") or []

    active_labels = events.get("active_labels") or []
    active_count = events.get("active_count", 0)

    support = zones.get("support")
    resistance = zones.get("resistance")
    mid = zones.get("mid")
    band_pct = zones.get("band_pct")

    lines = []
    lines.append(f"🧠 <b>Smart Snapshot تفصيلي</b> — <b>{symbol}</b>")
    lines.append("")
    lines.append(f"السعر: <b>{format_number(price, 2)}</b>")
    lines.append(f"التغير 24h: <b>{format_pct(change, 2, signed=True)}</b>")
    lines.append(f"High/Low: <b>{format_number(high, 2)}</b> / <b>{format_number(low, 2)}</b>")
    lines.append(f"النطاق: <b>{format_number(rng, 2)}%</b> — التقلب: <b>{format_number(vol, 1)}</b>/100")
    lines.append("")
    lines.append(f"⚠️ مستوى التنبيه: <b>{_alert_level_ar(level)}</b> (Shock: <b>{format_number(shock, 1)}</b>/100 | Boost: <b>{format_number(boost, 1)}</b>)")
    lines.append(f"🛡️ المخاطر: <b>{risk_level}</b> (Score ≈ <b>{format_number(risk_score, 1)}</b>)")
    lines.append("")
    lines.append(f"🏎️ السرعة: <b>{format_number(speed, 1)}</b> — 🧭 التسارع: <b>{format_number(accel, 1)}</b> — 🎯 ثقة الاتجاه: <b>{format_number(conf, 0)}%</b>")
    lines.append(f"🌪️ Regime: <b>{regime}</b> (prev: {prev_regime})")
    lines.append("")
    lines.append(f"📍 Zones: دعم <b>{format_number(support, 2)}</b> | منتصف <b>{format_number(mid, 2)}</b> | مقاومة <b>{format_number(resistance, 2)}</b> | Band% <b>{format_number(band_pct, 2)}</b>")
    lines.append("")

    if active_count:
        lines.append(f"🏛️ إشارات مؤسسية ({active_count}):")
        for lbl in active_labels[:8]:
            lines.append(f" • {lbl}")
        lines.append("")

    if reasons:
        lines.append("📌 أسباب التصنيف:")
        for r in reasons[:10]:
            lines.append(f" • {r}")

    lines.append("")
    lines.append("<b>IN CRYPTO Ai 🤖 — منظومة ذكاء اصطناعى شاملة لتحليل السوق فى الوقت الفعلى</b>")

    return "\n".join(lines).strip()
