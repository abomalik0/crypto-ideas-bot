"""
engine_schools.py

Advanced School Engine (V2)
- Registry-based architecture
- Multi-school ready
- Backward compatible with pick_school_report
"""

from __future__ import annotations
from typing import Any, Dict, Callable

# =====================================================
# Helpers
# =====================================================

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

# =====================================================
# Snapshot Extractor
# =====================================================

def _extract(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    metrics = snapshot.get("metrics") or {}
    risk = snapshot.get("risk") or {}
    pulse = snapshot.get("pulse") or {}
    events = snapshot.get("events") or {}
    alert = snapshot.get("alert") or {}
    zones = snapshot.get("zones") or {}

    return {
        "symbol": snapshot.get("symbol", "BTCUSDT"),
        "price": metrics.get("price"),
        "change": metrics.get("change_pct"),
        "range_pct": metrics.get("range_pct"),
        "vol": metrics.get("volatility_score"),
        "trend_bias": alert.get("trend_bias", "neutral"),
        "risk_level": risk.get("level", "low"),
        "risk_score": risk.get("score", 0),
        "zones": zones,
        "pulse": pulse,
        "events": events,
    }

# =====================================================
# 🧠 School Registry Engine
# =====================================================

SchoolBuilder = Callable[[Dict[str, Any]], str]
_SCHOOL_REGISTRY: Dict[str, SchoolBuilder] = {}

def register_school(name: str):
    def wrapper(func: SchoolBuilder):
        _SCHOOL_REGISTRY[name.lower()] = func
        return func
    return wrapper

def build_school_report(school: str, snapshot: Dict[str, Any]) -> str:
    key = (school or "smc").lower().strip()
    builder = _SCHOOL_REGISTRY.get(key)

    if not builder:
        return (
            "⚠️ <b>كود مدرسة غير معروف</b>\n"
            "المدارس المتاحة:\n"
            "• smc\n"
            "• ict\n"
            "• wyckoff\n"
            "• harmonic\n"
            "• time"
        )

    return builder(snapshot)

# =====================================================
# 🏛 SMC — Smart Money Concepts
# =====================================================

@register_school("smc")
def school_smc(snapshot: Dict[str, Any]) -> str:
    d = _extract(snapshot)
    return f"""
📘 <b>SMC — Smart Money Concepts</b>
<b>{d['symbol']}</b>

📊 الهيكلة:
• Trend Bias: <b>{d['trend_bias']}</b>
• Change: <b>{_pct(d['change'])}</b>
• Volatility: <b>{_fmt(d['vol'])}</b>

🏦 Zones:
• Support: {_fmt(d['zones'].get('support'))}
• Mid: {_fmt(d['zones'].get('mid'))}
• Resistance: {_fmt(d['zones'].get('resistance'))}

⚠️ Risk:
• Level: <b>{d['risk_level']}</b>
• Score: <b>{_fmt(d['risk_score'])}</b>

📌 الخلاصة:
السوق يتحرك وفق السيولة والهيكلة المؤسسية.
""".strip()

# =====================================================
# 🧩 ICT — Inner Circle Trader
# =====================================================

@register_school("ict")
def school_ict(snapshot: Dict[str, Any]) -> str:
    d = _extract(snapshot)
    mid = d["zones"].get("mid")

    pd = "غير متاح"
    try:
        if mid and d["price"]:
            pd = "Premium" if d["price"] > mid else "Discount"
    except Exception:
        pass

    return f"""
📘 <b>ICT — Inner Circle Trader</b>
<b>{d['symbol']}</b>

• Price: <b>{_fmt(d['price'])}</b>
• Premium / Discount: <b>{pd}</b>

💧 Liquidity Context:
• Equal Highs / Lows
• Fair Value Gaps
• Killzones (London / NY)

⚠️ Risk: <b>{d['risk_level']}</b>
""".strip()

# =====================================================
# 📦 Wyckoff
# =====================================================

@register_school("wyckoff")
def school_wyckoff(snapshot: Dict[str, Any]) -> str:
    d = _extract(snapshot)

    phase = "Accumulation / Distribution"
    if d["vol"] and d["vol"] > 55:
        phase = "Volatility Expansion / Shakeout"

    return f"""
📘 <b>Wyckoff Method</b>
<b>{d['symbol']}</b>

📊 Market Phase:
• {phase}

📈 Price Change: <b>{_pct(d['change'])}</b>
⚠️ Risk: <b>{d['risk_level']}</b>

📌 التركيز:
Effort vs Result + Volume Confirmation
""".strip()

# =====================================================
# 🌀 Harmonic (Pro Skeleton)
# =====================================================

@register_school("harmonic")
def school_harmonic(snapshot: Dict[str, Any]) -> str:
    d = _extract(snapshot)
    return f"""
📘 <b>Harmonic Patterns</b>
<b>{d['symbol']}</b>

🔍 Patterns:
• Gartley
• Bat
• Crab
• Butterfly
• AB=CD

📐 التركيز:
• Fibonacci Ratios
• PRZ Zones
• Confluence

⚠️ تنبيه:
النموذج لا يُتداول بدون تأكيد سعري.
""".strip()

# =====================================================
# ⏱ Time Master (Skeleton)
# =====================================================

@register_school("time")
def school_time(snapshot: Dict[str, Any]) -> str:
    d = _extract(snapshot)
    return f"""
📘 <b>Time Master Model</b>
<b>{d['symbol']}</b>

⏳ التركيز:
• Time Cycles
• Time Windows
• Fibonacci Time
• Gann / Bradley

📊 Change: <b>{_pct(d['change'])}</b>
⚠️ Risk: <b>{d['risk_level']}</b>
""".strip()

# =====================================================
# 🔁 Backward Compatibility
# =====================================================

def pick_school_report(school: str, snapshot: Dict[str, Any]) -> str:
    return build_school_report(school, snapshot)
