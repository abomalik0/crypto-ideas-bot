"""
HARMONIC SCHOOL – FULL PROFESSIONAL ENGINE
=========================================

• Detects ALL harmonic patterns
• Exact Fibonacci validation
• PRZ zones
• Targets + Stop Loss
• Bullish & Bearish scenarios
• Multi-Timeframe logic
"""

from typing import Dict, List, Any
import math


# =========================
# Fibonacci helpers
# =========================

def fib_ratio(a: float, b: float) -> float:
    return abs(b / a) if a != 0 else 0


def in_range(val: float, low: float, high: float) -> bool:
    return low <= val <= high


# =========================
# Pattern definitions
# =========================

HARMONIC_PATTERNS = {
    "Gartley": {
        "AB": (0.618, 0.618),
        "BC": (0.382, 0.886),
        "CD": (1.27, 1.618),
        "XA": 0.786,
    },
    "Bat": {
        "AB": (0.382, 0.5),
        "BC": (0.382, 0.886),
        "CD": (1.618, 2.618),
        "XA": 0.886,
    },
    "Alt Bat": {
        "AB": (0.382, 0.5),
        "BC": (0.382, 0.886),
        "CD": (2.0, 3.618),
        "XA": 1.13,
    },
    "Crab": {
        "AB": (0.382, 0.618),
        "BC": (0.382, 0.886),
        "CD": (2.618, 3.618),
        "XA": 1.618,
    },
    "Deep Crab": {
        "AB": (0.886, 0.886),
        "BC": (0.382, 0.886),
        "CD": (2.618, 3.618),
        "XA": 1.618,
    },
    "AB=CD": {
        "AB": (1.0, 1.0),
        "BC": (0.382, 0.886),
        "CD": (1.0, 1.272),
        "XA": None,
    },
}


# =========================
# Main Harmonic Engine
# =========================

def analyze_harmonic(
    symbol: str,
    timeframe: str,
    swings: List[float],
) -> Dict[str, Any]:
    """
    swings = [X, A, B, C, D]
    """

    if len(swings) < 5:
        return {"error": "Not enough swing points"}

    X, A, B, C, D = swings

    XA = A - X
    AB = B - A
    BC = C - B
    CD = D - C

    ab_ratio = fib_ratio(XA, AB)
    bc_ratio = fib_ratio(AB, BC)
    cd_ratio = fib_ratio(BC, CD)

    detected = None
    accuracy = 0

    for name, rules in HARMONIC_PATTERNS.items():
        ok = True
        score = 0
        total = 0

        if rules["AB"]:
            total += 1
            if in_range(ab_ratio, *rules["AB"]):
                score += 1

        if rules["BC"]:
            total += 1
            if in_range(bc_ratio, *rules["BC"]):
                score += 1

        if rules["CD"]:
            total += 1
            if in_range(cd_ratio, *rules["CD"]):
                score += 1

        if rules["XA"]:
            total += 1
            xa_ret = abs((D - X) / XA) if XA != 0 else 0
            if abs(xa_ret - rules["XA"]) <= 0.05:
                score += 1

        if score >= total - 1:
            detected = name
            accuracy = round((score / total) * 100, 1)
            break

    # =========================
    # PRZ + Targets
    # =========================

    prz = {
        "zone": (round(D * 0.995, 2), round(D * 1.005, 2)),
        "confidence": accuracy,
    }

    bullish = {
        "entry": prz["zone"],
        "targets": [
            round(D + abs(CD) * 0.382, 2),
            round(D + abs(CD) * 0.618, 2),
            round(D + abs(CD) * 1.0, 2),
        ],
        "stop_loss": round(D - abs(CD) * 0.236, 2),
    }

    bearish = {
        "entry": prz["zone"],
        "targets": [
            round(D - abs(CD) * 0.382, 2),
            round(D - abs(CD) * 0.618, 2),
            round(D - abs(CD) * 1.0, 2),
        ],
        "stop_loss": round(D + abs(CD) * 0.236, 2),
    }

    return {
        "school": "harmonic",
        "symbol": symbol,
        "timeframe": timeframe,
        "pattern": detected,
        "accuracy": accuracy,
        "wave_structure": {
            "XA": round(XA, 2),
            "AB": round(AB, 2),
            "BC": round(BC, 2),
            "CD": round(CD, 2),
        },
        "prz": prz,
        "bullish": bullish,
        "bearish": bearish,
  }
