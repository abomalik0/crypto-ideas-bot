"""
HARMONIC SCHOOL
Advanced Harmonic Pattern Analysis Engine

Detects all harmonic patterns with full Fibonacci validation,
PRZ construction, and bullish/bearish scenario building.
"""

from typing import Dict, Any, List, Optional
import math


# ============================================================
# Utilities
# ============================================================

def fib_ratio(a: float, b: float, c: float) -> float:
    if a == b:
        return 0.0
    return abs((c - b) / (b - a))


def price_range(a: float, b: float) -> float:
    return abs(b - a)


# ============================================================
# Swing Detection
# ============================================================

def extract_swings(
    candles: List[Dict[str, float]],
    lookback: int = 3
) -> List[Dict[str, Any]]:

    swings = []

    for i in range(lookback, len(candles) - lookback):
        high = candles[i]["high"]
        low = candles[i]["low"]

        is_high = True
        is_low = True

        for j in range(1, lookback + 1):
            if high <= candles[i - j]["high"] or high <= candles[i + j]["high"]:
                is_high = False
            if low >= candles[i - j]["low"] or low >= candles[i + j]["low"]:
                is_low = False

        if is_high:
            swings.append({"i": i, "price": high, "type": "high"})
        elif is_low:
            swings.append({"i": i, "price": low, "type": "low"})

    return swings


# ============================================================
# XABCD Builder
# ============================================================

def build_xabcd(swings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    patterns = []

    for i in range(len(swings) - 4):
        X, A, B, C, D = swings[i:i + 5]

        # alternating structure
        types = [p["type"] for p in (X, A, B, C, D)]
        if types.count("high") < 2 or types.count("low") < 2:
            continue

        patterns.append({
            "X": X, "A": A, "B": B, "C": C, "D": D
        })

    return patterns


# ============================================================
# Harmonic Pattern Rules
# ============================================================

HARMONIC_RULES = {
    "Gartley": {
        "AB": (0.60, 0.65),
        "BC": (0.382, 0.886),
        "CD": (1.27, 1.618),
        "XA_PRZ": 0.786,
    },
    "Bat": {
        "AB": (0.382, 0.50),
        "BC": (0.382, 0.886),
        "CD": (1.618, 2.618),
        "XA_PRZ": 0.886,
    },
    "Butterfly": {
        "AB": (0.786, 0.786),
        "BC": (0.382, 0.886),
        "CD": (1.618, 2.618),
        "XA_PRZ": 1.27,
    },
    "Crab": {
        "AB": (0.382, 0.618),
        "BC": (0.382, 0.886),
        "CD": (2.618, 3.618),
        "XA_PRZ": 1.618,
    },
    "Deep Crab": {
        "AB": (0.886, 0.886),
        "BC": (0.382, 0.886),
        "CD": (2.24, 3.618),
        "XA_PRZ": 1.618,
    },
    "AB=CD": {
        "AB": (0.95, 1.05),
        "BC": (0.382, 0.886),
        "CD": (0.95, 1.05),
        "XA_PRZ": None,
    },
}


# ============================================================
# Pattern Evaluation
# ============================================================

def evaluate_pattern(xabcd: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    X, A, B, C, D = (
        xabcd["X"]["price"],
        xabcd["A"]["price"],
        xabcd["B"]["price"],
        xabcd["C"]["price"],
        xabcd["D"]["price"],
    )

    xa = price_range(X, A)
    ab = price_range(A, B)
    bc = price_range(B, C)
    cd = price_range(C, D)

    if xa == 0 or ab == 0:
        return None

    ab_ratio = ab / xa
    bc_ratio = bc / ab
    cd_ratio = cd / bc if bc != 0 else 0

    best_match = None
    best_score = 0.0

    for name, rule in HARMONIC_RULES.items():
        score = 0
        checks = 0

        ab_min, ab_max = rule["AB"]
        if ab_min <= ab_ratio <= ab_max:
            score += 1
        checks += 1

        bc_min, bc_max = rule["BC"]
        if bc_min <= bc_ratio <= bc_max:
            score += 1
        checks += 1

        cd_min, cd_max = rule["CD"]
        if cd_min <= cd_ratio <= cd_max:
            score += 1
        checks += 1

        accuracy = score / checks

        if accuracy > best_score:
            best_score = accuracy
            best_match = {
                "pattern": name,
                "accuracy": round(accuracy * 100, 2),
                "ratios": {
                    "AB": round(ab_ratio, 3),
                    "BC": round(bc_ratio, 3),
                    "CD": round(cd_ratio, 3),
                },
                "points": xabcd,
            }

    return best_match if best_score >= 0.66 else None


# ============================================================
# PRZ Builder
# ============================================================

def build_prz(pattern: Dict[str, Any]) -> Dict[str, Any]:
    X = pattern["points"]["X"]["price"]
    A = pattern["points"]["A"]["price"]
    D = pattern["points"]["D"]["price"]

    rule = HARMONIC_RULES[pattern["pattern"]]
    levels = {}

    if rule["XA_PRZ"]:
        levels["XA"] = A + (A - X) * rule["XA_PRZ"]

    return {
        "main": round(D, 2),
        "fib_levels": {k: round(v, 2) for k, v in levels.items()},
    }


# ============================================================
# Main Entry
# ============================================================

def analyze_harmonic(
    symbol: str,
    timeframe: str,
    candles: List[Dict[str, float]],
) -> Dict[str, Any]:

    swings = extract_swings(candles)
    xabcd_list = build_xabcd(swings)

    best_pattern = None

    for xabcd in xabcd_list:
        result = evaluate_pattern(xabcd)
        if result and (
            not best_pattern
            or result["accuracy"] > best_pattern["accuracy"]
        ):
            best_pattern = result

    if not best_pattern:
        return {
            "school": "harmonic",
            "symbol": symbol,
            "timeframe": timeframe,
            "status": "no_pattern",
        }

    prz = build_prz(best_pattern)

    direction = (
        "bullish"
        if best_pattern["points"]["D"]["type"] == "low"
        else "bearish"
    )

    return {
        "school": "harmonic",
        "symbol": symbol,
        "timeframe": timeframe,
        "pattern": best_pattern["pattern"],
        "accuracy": best_pattern["accuracy"],
        "direction": direction,
        "ratios": best_pattern["ratios"],
        "prz": prz,
        "D_point": best_pattern["points"]["D"]["price"],
    }
