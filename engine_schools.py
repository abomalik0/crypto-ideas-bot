"""
engine_schools.py

✅ الهدف:
محرك مدارس تحليل (School Engine)
- اختيار أي مدرسة يدويًا
- تحليل أي عملة (SYMBOL)
- قابل للتوسيع بدون كسر الشغل الحالي
"""

from __future__ import annotations
from typing import Any, Dict, Callable


# ========================
# Helpers
# ========================

def _fmt(x: Any, digits: int = 2) -> str:
    try:
        if x is None:
            return "-"
        return f"{float(x):.{digits}f}"
    except Exception:
        return str(x)


def _pct(x: Any, digits: int = 2) -> str:
    try:
        if x is None:
            return "-"
        v = float(x)
        return f"{v:+.{digits}f}%"
    except Exception:
        return str(x)


def _ar_trend(trend_bias: str, change_pct: float) -> str:
    if trend_bias == "bull":
        return "صاعد"
    if trend_bias == "bear":
        return "هابط"
    if change_pct > 0.2:
        return "صاعد (ضعيف)"
    if change_pct < -0.2:
        return "هابط (ضعيف)"
    return "محايد"


def _risk_level_ar(level: str) -> str:
    return {
        "low": "منخفض",
        "medium": "متوسط",
        "high": "مرتفع",
    }.get(level, str(level))


def _alert_level_ar(level: str) -> str:
    return {
        "low": "هادئ",
        "medium": "متوسط",
        "high": "قوي",
        "critical": "خطير جدًا",
    }.get(level, str(level))


def _zones_text(zones: Dict[str, Any]) -> str:
    return (
        f"دعم <b>{_fmt(zones.get('support'),2)}</b> | "
        f"منتصف <b>{_fmt(zones.get('mid'),2)}</b> | "
        f"مقاومة <b>{_fmt(zones.get('resistance'),2)}</b> | "
        f"Band% <b>{_fmt(zones.get('band_pct'),2)}</b>"
    )


def _extract(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    metrics = snapshot.get("metrics") or {}
    risk = snapshot.get("risk") or {}
    pulse = snapshot.get("pulse") or {}
    events = snapshot.get("events") or {}
    alert = snapshot.get("alert") or {}
    zones = snapshot.get("zones") or {}

    return {
        "price": float(metrics.get("price") or 0),
        "change": float(metrics.get("change_pct") or 0),
        "range_pct": float(metrics.get("range_pct") or 0),
        "vol": float(metrics.get("volatility_score") or 0),
        "speed": float(pulse.get("speed_index") or 0),
        "accel": float(pulse.get("accel_index") or 0),
        "conf": float(pulse.get("direction_confidence") or 0),
        "trend_bias": str(alert.get("trend_bias") or "neutral"),
        "risk_level": str(risk.get("level") or "low"),
        "risk_score": float(risk.get("score") or 0),
        "alert_level": str(alert.get("level") or "low"),
        "shock": float(alert.get("shock_score") or 0),
        "events_labels": events.get("active_labels") or [],
        "events_count": int(events.get("active_count") or 0),
        "zones": zones,
    }


# ========================
# SMC
# ========================

def build_smc_report(snapshot: Dict[str, Any]) -> str:
    symbol = snapshot.get("symbol", "BTCUSDT")
    d = _extract(snapshot)

    bos = abs(d["change"]) >= 1.2 and d["speed"] >= 25
    choch = bos and abs(d["accel"]) >= 10

    imb = "منخفض"
    if d["vol"] >= 55 or d["range_pct"] >= 6:
        imb = "مرتفع"
    elif d["vol"] >= 35 or d["range_pct"] >= 4:
        imb = "متوسط"

    return f"""
📊 <b>SMC تحليل</b> — <b>{symbol}</b>

السعر: <b>{_fmt(d['price'])}</b>
التغير: <b>{_pct(d['change'])}</b>

🧭 الهيكل: <b>{_ar_trend(d['trend_bias'], d['change'])}</b>
🛡️ المخاطرة: <b>{_risk_level_ar(d['risk_level'])}</b>
⚠️ التنبيه: <b>{_alert_level_ar(d['alert_level'])}</b>

📍 POI:
{_zones_text(d['zones'])}

⚖️ Imbalance: <b>{imb}</b>
{"✅ BOS محتمل" if bos else "— لا يوجد BOS"}
{"⚠️ CHOCH محتمل" if choch else ""}

<b>IN CRYPTO Ai 🤖 — SMC</b>
""".strip()


# ========================
# ICT
# ========================

def build_ict_report(snapshot: Dict[str, Any]) -> str:
    symbol = snapshot.get("symbol", "BTCUSDT")
    d = _extract(snapshot)
    zones = d["zones"]

    mid = zones.get("mid")
    pd = "غير متاح"
    if mid:
        pd = "Premium" if d["price"] > mid else "Discount"

    return f"""
🧩 <b>ICT تحليل</b> — <b>{symbol}</b>

السعر: <b>{_fmt(d['price'])}</b>
Premium/Discount: <b>{pd}</b>

📍 Zones:
{_zones_text(zones)}

⚠️ Alert: <b>{_alert_level_ar(d['alert_level'])}</b>

<b>IN CRYPTO Ai 🤖 — ICT</b>
""".strip()


# ========================
# Wyckoff
# ========================

def build_wyckoff_report(snapshot: Dict[str, Any]) -> str:
    symbol = snapshot.get("symbol", "BTCUSDT")
    d = _extract(snapshot)

    phase = "Neutral"
    if d["trend_bias"] == "bull" and d["vol"] < 35:
        phase = "Accumulation / Markup"
    elif d["trend_bias"] == "bear" and d["vol"] < 35:
        phase = "Distribution / Markdown"
    elif d["vol"] >= 55:
        phase = "Transition"

    return f"""
📦 <b>Wyckoff تحليل</b> — <b>{symbol}</b>

السعر: <b>{_fmt(d['price'])}</b>
Phase: <b>{phase}</b>

Speed: <b>{_fmt(d['speed'],1)}</b> | Accel: <b>{_fmt(d['accel'],1)}</b>

📍 Zones:
{_zones_text(d['zones'])}

<b>IN CRYPTO Ai 🤖 — Wyckoff</b>
""".strip()


# ========================
# School Registry
# ========================

SCHOOL_REGISTRY: Dict[str, Callable[[Dict[str, Any]], str]] = {
    "smc": build_smc_report,
    "ict": build_ict_report,
    "wyckoff": build_wyckoff_report,
}


def pick_school_report(school: str, snapshot: Dict[str, Any]) -> str:
    """
    Manual School Selector
    - school: أي اسم مدرسة
    - snapshot: بيانات العملة
    """
    key = (school or "smc").strip().lower()
    builder = SCHOOL_REGISTRY.get(key, build_smc_report)
    return builder(snapshot)
