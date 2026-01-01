"""
HARMONIC SCHOOL – CORE ENGINE
============================

• Detect harmonic patterns using swing points
• Validate Fibonacci ratios
• Build PRZ zones
• Generate targets & stop loss
• Pure Harmonic logic only (no SMC / no ICT)
"""

from typing import List, Dict, Any
import math


# =========================
# Helpers
# =========================

def _fib_ratio(a: float, b: float) -> float:
    if a == 0:
        return 0.0
    return abs(b / a)


def _in_range(value: float, low: float, high: float, tolerance: float = 0.03) -> bool:
    return (low - tolerance) <= value <= (high + tolerance)


def _determine_direction(C: float, D: float) -> str:
    if D < C:
        return "bullish"
    elif D > C:
        return "bearish"
    return "neutral"


def _strength_label(confidence: float) -> str:
    if confidence >= 85:
        return "🔥 قوي جدًا"
    elif confidence >= 70:
        return "✅ قوي"
    elif confidence >= 55:
        return "⚠️ متوسط"
    return "❌ ضعيف"


# =========================
# Harmonic Pattern Rules
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
# Core Harmonic Analyzer
# =========================

def analyze_harmonic(
    symbol: str,
    timeframe: str,
    swings: List[float],
) -> Dict[str, Any]:
    """
    swings = [X, A, B, C, D]
    """

    if not swings or len(swings) < 5:
        return {
            "valid": False,
            "school": "harmonic",
            "reason": "Not enough swing points",
        }

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

    detected_pattern = None
    confidence = 0.0

    for name, rules in HARMONIC_RULES.items():
        score = 0
        total = len(rules)

        for leg, (low, high) in rules.items():
            if _in_range(ratios.get(leg, 0), low, high):
                score += 1

        if score >= total - 1:
            detected_pattern = name
            confidence = round((score / total) * 100, 1)
            break

    if not detected_pattern:
        return {
            "valid": False,
            "school": "harmonic",
            "symbol": symbol,
            "timeframe": timeframe,
            "reason": "No complete harmonic pattern detected",
        }

    direction = _determine_direction(C, D)
    strength = _strength_label(confidence)

    # =========================
    # PRZ + Targets + Stop
    # =========================

    prz_low = round(D * 0.995, 2)
    prz_high = round(D * 1.005, 2)

    bullish_targets = [
        round(D + abs(CD) * 0.382, 2),
        round(D + abs(CD) * 0.618, 2),
        round(D + abs(CD) * 1.0, 2),
    ]

    bearish_targets = [
        round(D - abs(CD) * 0.382, 2),
        round(D - abs(CD) * 0.618, 2),
        round(D - abs(CD) * 1.0, 2),
    ]

    stop_loss = (
        round(D - abs(CD) * 0.236, 2)
        if direction == "bullish"
        else round(D + abs(CD) * 0.236, 2)
    )

    return {
        "valid": True,
        "school": "harmonic",
        "symbol": symbol,
        "timeframe": timeframe,
        "pattern": detected_pattern,
        "confidence": confidence,
        "strength": strength,
        "direction": direction,
        "points": {
            "X": round(X, 2),
            "A": round(A, 2),
            "B": round(B, 2),
            "C": round(C, 2),
            "D": round(D, 2),
        },
        "ratios": {k: round(v, 3) for k, v in ratios.items()},
        "prz": (prz_low, prz_high),
        "targets": bullish_targets if direction == "bullish" else bearish_targets,
        "stop_loss": stop_loss,
    }
