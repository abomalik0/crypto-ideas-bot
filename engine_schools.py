"""
engine_schools.py

✅ الهدف: بناء تقارير/شرح من "مدارس تحليل" مختلفة (SMC / ICT / Wyckoff)
بشكل مستقل عن analysis_engine.py لتسهيل التطوير وإضافة مدارس جديدة لاحقاً.

ملاحظة: هذا الملف جاهز للربط التدريجي لاحقاً بدون كسر الشغل الحالي.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


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


def _zones_text(zones: Dict[str, Any]) -> str:
    sup = zones.get("support")
    mid = zones.get("mid")
    res = zones.get("resistance")
    band = zones.get("band_pct")
    return f"دعم <b>{_fmt(sup,2)}</b> | منتصف <b>{_fmt(mid,2)}</b> | مقاومة <b>{_fmt(res,2)}</b> | Band% <b>{_fmt(band,2)}</b>"


def _extract(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    metrics = snapshot.get("metrics") or {}
    risk = snapshot.get("risk") or {}
    pulse = snapshot.get("pulse") or {}
    events = snapshot.get("events") or {}
    alert = snapshot.get("alert") or {}
    zones = snapshot.get("zones") or {}

    price = float(metrics.get("price") or 0.0)
    change = float(metrics.get("change_pct") or 0.0)
    range_pct = float(metrics.get("range_pct") or 0.0)
    vol = float(metrics.get("volatility_score") or 0.0)

    speed = float(pulse.get("speed_index") or 0.0)
    accel = float(pulse.get("accel_index") or 0.0)
    conf = float(pulse.get("direction_confidence") or 0.0)
    regime = pulse.get("regime")

    risk_level = str(risk.get("level") or "low")
    risk_score = float(risk.get("score") or 0.0)

    level = str(alert.get("level") or "low")
    shock = float(alert.get("shock_score") or 0.0)
    trend_bias = str(alert.get("trend_bias") or "neutral")

    active_labels = events.get("active_labels") or []
    active_count = int(events.get("active_count") or 0)

    return {
        "price": price,
        "change": change,
        "range_pct": range_pct,
        "vol": vol,
        "speed": speed,
        "accel": accel,
        "conf": conf,
        "regime": regime,
        "risk_level": risk_level,
        "risk_score": risk_score,
        "level": level,
        "shock": shock,
        "trend_bias": trend_bias,
        "events_labels": active_labels,
        "events_count": active_count,
        "zones": zones,
    }


# ------------------------
# SMC Report
# ------------------------
def build_smc_report(snapshot: Dict[str, Any]) -> str:
    """
    تقرير SMC مبسط عملي:
    - Market Structure (trend)
    - POI (zones)
    - Imbalance (band/vol)
    - BOS/CHOCH (استدلال بسيط من السرعة/التسارع + تغير السعر)
    """
    symbol = snapshot.get("symbol", "BTCUSDT")
    d = _extract(snapshot)

    trend_txt = _ar_trend(d["trend_bias"], d["change"])
    risk_txt = _risk_level_ar(d["risk_level"])
    alert_txt = _alert_level_ar(d["level"])

    # استدلال BOS/CHOCH بسيط
    bos = False
    choch = False
    if abs(d["change"]) >= 1.2 and d["speed"] >= 25:
        bos = True
    if bos and abs(d["accel"]) >= 10:
        choch = True

    bos_txt = "✅ BOS محتمل" if bos else "— لا يوجد BOS واضح"
    choch_txt = "⚠️ CHOCH محتمل" if choch else "— لا يوجد CHOCH واضح"

    imb = "منخفض"
    if d["vol"] >= 55 or d["range_pct"] >= 6:
        imb = "مرتفع"
    elif d["vol"] >= 35 or d["range_pct"] >= 4:
        imb = "متوسط"

    events_block = ""
    if d["events_count"] > 0:
        labels = "\n".join(f"• {x}" for x in d["events_labels"][:6])
        events_block = f"\n\n🏛️ <b>Institutional Signals</b> ({d['events_count']}):\n{labels}"

    msg = f"""
📊 <b>SMC تحليل</b> — <b>{symbol}</b>

السعر: <b>{_fmt(d['price'],2)}</b>
التغير 24h: <b>{_pct(d['change'],2)}</b>
النطاق: <b>{_fmt(d['range_pct'],2)}%</b> — التقلب: <b>{_fmt(d['vol'],1)}</b>/100

🧭 <b>Market Structure</b>: <b>{trend_txt}</b>
⚠️ <b>Alert</b>: <b>{alert_txt}</b> (Shock: <b>{_fmt(d['shock'],1)}</b>/100)
🛡️ <b>Risk</b>: <b>{risk_txt}</b> (Score ≈ <b>{_fmt(d['risk_score'],1)}</b>)

📍 <b>POI / Zones</b>:
{_zones_text(d['zones'])}

⚖️ <b>Imbalance</b>: <b>{imb}</b>
{bos_txt}
{choch_txt}{events_block}

<b>IN CRYPTO Ai 🤖 — SMC Mode</b>
""".strip()

    return msg


# ------------------------
# ICT Report (light)
# ------------------------
def build_ict_report(snapshot: Dict[str, Any]) -> str:
    """
    ICT مبسط:
    - Premium/Discount حسب mid
    - Liquidity hints
    """
    symbol = snapshot.get("symbol", "BTCUSDT")
    d = _extract(snapshot)
    zones = d["zones"]

    mid = zones.get("mid")
    price = d["price"]

    premium_discount = "غير متاح"
    try:
        if mid is not None and price:
            premium_discount = "Premium" if float(price) > float(mid) else "Discount"
    except Exception:
        pass

    liq_hint = "سيولة طبيعية"
    if d["events_count"] >= 2 or d["vol"] >= 60:
        liq_hint = "احتمال Liquidity Sweep / Stop Hunt"
    elif abs(d["change"]) >= 2.0:
        liq_hint = "اندفاع سيولة واضح (Breakout/Breakdown)"

    msg = f"""
🧩 <b>ICT تحليل</b> — <b>{symbol}</b>

السعر: <b>{_fmt(d['price'],2)}</b> | التغير: <b>{_pct(d['change'],2)}</b>
Premium/Discount: <b>{premium_discount}</b>

📍 Zones:
{_zones_text(zones)}

💧 Liquidity Hint: <b>{liq_hint}</b>
⚠️ Alert: <b>{_alert_level_ar(d['level'])}</b> (Shock: <b>{_fmt(d['shock'],1)}</b>/100)

<b>IN CRYPTO Ai 🤖 — ICT Mode</b>
""".strip()

    return msg


# ------------------------
# Wyckoff Report (light)
# ------------------------
def build_wyckoff_report(snapshot: Dict[str, Any]) -> str:
    """
    Wyckoff مبسط:
    - Accumulation/Distribution استدلالي من trend + volatility
    """
    symbol = snapshot.get("symbol", "BTCUSDT")
    d = _extract(snapshot)

    phase = "Neutral"
    if d["trend_bias"] == "bull" and d["vol"] < 35:
        phase = "Accumulation / Markup"
    elif d["trend_bias"] == "bear" and d["vol"] < 35:
        phase = "Distribution / Markdown"
    elif d["vol"] >= 55:
        phase = "Transition / Volatility Expansion"

    effort_result = "Effort متوسط"
    if d["speed"] >= 30 and abs(d["change"]) >= 1.5:
        effort_result = "Effort كبير (اندفاع قوي)"
    elif d["speed"] < 10 and abs(d["change"]) < 0.5:
        effort_result = "Effort ضعيف (تجميع/توزيع)"

    msg = f"""
📦 <b>Wyckoff تحليل</b> — <b>{symbol}</b>

السعر: <b>{_fmt(d['price'],2)}</b>
التغير 24h: <b>{_pct(d['change'],2)}</b>
Phase: <b>{phase}</b>

🏎️ Speed: <b>{_fmt(d['speed'],1)}</b> | Accel: <b>{_fmt(d['accel'],1)}</b> | Conf: <b>{_fmt(d['conf'],0)}%</b>
Effort/Result: <b>{effort_result}</b>

📍 Zones:
{_zones_text(d['zones'])}

⚠️ Alert: <b>{_alert_level_ar(d['level'])}</b> (Shock: <b>{_fmt(d['shock'],1)}</b>/100)

<b>IN CRYPTO Ai 🤖 — Wyckoff Mode</b>
""".strip()

    return msg


def pick_school_report(school: str, snapshot: Dict[str, Any]) -> str:
    """
    school can be: 'smc' | 'ict' | 'wyckoff'
    default: smc
    """
    s = (school or "").strip().lower()
    if s in ("ict", "i", "inner"):
        return build_ict_report(snapshot)
    if s in ("wyckoff", "w", "wy"):
        return build_wyckoff_report(snapshot)
    return build_smc_report(snapshot)
