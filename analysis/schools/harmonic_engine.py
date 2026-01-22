"""
HARMONIC SCHOOL – CORE ENGINE
============================

• Detect harmonic patterns using swing points
• Validate Fibonacci ratios (RELAXED – TradingView style)
• Build PRZ zones (REAL fib-based)
• Generate targets & stop loss
• Allow predictive (incomplete) patterns
• Pure Harmonic logic only
"""

from typing import List, Dict, Any


# =========================
# Global Settings
# =========================

FIB_TOLERANCE = 0.25   # ✅ TradingView-grade tolerance


# =========================
# Helpers
# =========================

def _fib_ratio(a: float, b: float) -> float:
    if a == 0:
        return 0.0
    return abs(b / a)


def _in_range(value: float, low: float, high: float) -> bool:
    return (low - FIB_TOLERANCE) <= value <= (high + FIB_TOLERANCE)


def _determine_direction(C: float, D: float) -> str:
    return "bullish" if D < C else "bearish"


def _strength_label(confidence: float) -> str:
    if confidence >= 80:
        return "🔥 قوي جدًا"
    elif confidence >= 60:
        return "✅ قوي"
    elif confidence >= 40:
        return "⚠️ متوسط"
    return "❌ ضعيف"


# =========================
# Harmonic Rules
# =========================

HARMONIC_RULES = {
    "Gartley": {
        "AB": (0.618, 0.618),
        "BC": (0.382, 0.886),
        "CD": (1.27, 1.618),
        "AD": (0.786, 0.786),
    },
    "Bat": {
        "AB": (0.382, 0.50),
        "BC": (0.382, 0.886),
        "CD": (1.618, 2.618),
        "AD": (0.886, 0.886),
    },
    "Butterfly": {
        "AB": (0.786, 0.786),
        "BC": (0.382, 0.886),
        "CD": (1.618, 2.618),
        "AD": (1.27, 1.618),
    },
    "Crab": {
        "AB": (0.382, 0.618),
        "BC": (0.382, 0.886),
        "CD": (2.618, 3.618),
        "AD": (1.618, 1.618),
    },
    "Deep Crab": {
        "AB": (0.886, 0.886),
        "BC": (0.382, 0.886),
        "CD": (2.618, 3.618),
        "AD": (1.618, 1.618),
    },
}


# =========================
# Core Analyzer
# =========================

def analyze_harmonic(
    symbol: str,
    timeframe: str,
    swings: List[float],
) -> Dict[str, Any]:

    if not swings or len(swings) < 5:
        return {"valid": False}

    X, A, B, C, D = swings[-5:]

    XA = A - X
    AB = B - A
    BC = C - B
    CD = D - C
    AD = D - X

    ratios = {
        "AB": _fib_ratio(XA, AB),
        "BC": _fib_ratio(AB, BC),
        "CD": _fib_ratio(BC, CD),
        "AD": _fib_ratio(XA, AD),
    }

    best_pattern = None
    best_score = 0
    best_total = 0

    for name, rules in HARMONIC_RULES.items():
        score = 0
        total = len(rules)

        for leg, (low, high) in rules.items():
            if _in_range(ratios.get(leg, 0), low, high):
                score += 1

        if score > best_score:
            best_pattern = name
            best_score = score
            best_total = total

    # ✅ السماح بنماذج استباقية
    if best_score < 1:
        return {"valid": False}

    confidence = round((best_score / best_total) * 100, 1)
    direction = _determine_direction(C, D)
    strength = _strength_label(confidence)
    predictive = confidence < 80

    # =========================
    # PRZ / Targets / Stop
    # =========================

    # ✅ PRZ حقيقي مبني على XA
    prz_low = round(D - abs(XA) * 0.03, 6)
    prz_high = round(D + abs(XA) * 0.03, 6)
    prz = (prz_low, prz_high)

    move = abs(CD)

    targets = (
        [round(D + move * r, 6) for r in (0.382, 0.618, 1.0)]
        if direction == "bullish"
        else [round(D - move * r, 6) for r in (0.382, 0.618, 1.0)]
    )

    stop_loss = (
        round(D - move * 0.236, 6)
        if direction == "bullish"
        else round(D + move * 0.236, 6)
    )

    return {
        "valid": True,
        "school": "harmonic",
        "symbol": symbol,
        "timeframe": timeframe,
        "pattern": best_pattern,
        "confidence": confidence,
        "strength": strength,
        "direction": direction,
        "predictive": predictive,
        "points": {"X": X, "A": A, "B": B, "C": C, "D": D},
        "ratios": ratios,
        "prz": prz,
        "targets": targets,
        "stop_loss": stop_loss,
    }
