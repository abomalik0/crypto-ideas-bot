"""
engine_schools.py

Advanced School Engine (V2)
- Registry-based architecture
- Multi-school / Multi-symbol ready
- Backward compatible with old pick_school_report
"""

from __future__ import annotations
from typing import Any, Dict, Callable

# =====================================================
# Helpers (كما هى – بدون تغيير)
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
# Snapshot Extractor (كما هو)
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
    key = (school or "smc").lower()
    builder = _SCHOOL_REGISTRY.get(key)

    if not builder:
        return f"❌ لا توجد مدرسة تحليل باسم: {school}"

    return builder(snapshot)

# =====================================================
# 🏛 SMC — FULL
# =====================================================

@register_school("smc")
def school_smc(snapshot: Dict[str, Any]) -> str:
    d = _extract(snapshot)
    return f"""
📘 SMC — Smart Money Concepts — تحليل {d['symbol']}

🔍 مقدمة:
تحليل حركة السعر من منظور المؤسسات (Liquidity / Structure).

📊 الهيكلة:
• Trend Bias: {d['trend_bias']}
• Change: {_pct(d['change'])}
• Volatility: {_fmt(d['vol'])}

🏦 Zones:
{d['zones']}

⚠️ Risk:
• Level: {d['risk_level']}
• Score: {_fmt(d['risk_score'])}

📌 الخلاصة:
السلوك المؤسسي هو العامل الحاسم.
""".strip()

# =====================================================
# 🧩 ICT
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
📘 ICT — Inner Circle Trader — {d['symbol']}

• Price: {_fmt(d['price'])}
• Premium / Discount: {pd}

💧 Liquidity Context:
• Equal Highs / Lows
• FVG Zones
• Killzones (London / NY)

⚠️ Risk: {d['risk_level']}
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
📘 Wyckoff — {d['symbol']}

📊 Phase:
• Current Phase: {phase}

📈 Price Change: {_pct(d['change'])}
⚠️ Risk: {d['risk_level']}
""".strip()

# =====================================================
# 🌀 Harmonic (Pro Skeleton – جاهز للتوسعة)
# =====================================================

@register_school("harmonic")
def school_harmonic(snapshot: Dict[str, Any]) -> str:
    d = _extract(snapshot)
    return f"""
📘 Harmonic Patterns — {d['symbol']}

🔍 Patterns:
• Gartley
• Bat
• Crab
• Butterfly
• AB=CD

📐 Focus:
• Fibonacci Ratios
• PRZ Zones
• Confluence

⚠️ ملاحظة:
النموذج لا يُتداول بدون تأكيد شموع.
""".strip()

# =====================================================
# ⏱ Time Master (Skeleton جاهز)
# =====================================================

@register_school("time")
def school_time(snapshot: Dict[str, Any]) -> str:
    d = _extract(snapshot)
    return f"""
📘 Time Master Model — {d['symbol']}

⏳ Focus:
• Cycles
• Time Windows
• Fibonacci Time
• Gann / Bradley

📊 Change: {_pct(d['change'])}
⚠️ Risk: {d['risk_level']}
""".strip()

# =====================================================
# 🧱 Backward Compatibility
# =====================================================

def pick_school_report(school: str, snapshot: Dict[str, Any]) -> str:
    return build_school_report(school, snapshot)
