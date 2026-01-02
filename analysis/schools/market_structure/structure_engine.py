"""
MARKET STRUCTURE – CORE ENGINE
==============================

• Detect swing highs & lows
• Classify structure (HH, HL, LH, LL)
• Determine overall trend
• Pure price action (no indicators)
"""

from typing import List, Dict


# =========================
# Swing Detection
# =========================

def detect_structure_swings(
    candles: List[Dict],
    lookback: int = 3
) -> List[Dict]:
    """
    Detect swing highs and lows from candles.

    Output:
    [
        {
            "index": int,
            "price": float,
            "type": "high" | "low"
        }
    ]
    """

    swings = []

    for i in range(lookback, len(candles) - lookback):
        high = candles[i]["high"]
        low = candles[i]["low"]

        is_swing_high = True
        is_swing_low = True

        for j in range(1, lookback + 1):
            if high <= candles[i - j]["high"] or high <= candles[i + j]["high"]:
                is_swing_high = False
            if low >= candles[i - j]["low"] or low >= candles[i + j]["low"]:
                is_swing_low = False

        if is_swing_high:
            swings.append({
                "index": i,
                "price": high,
                "type": "high"
            })

        elif is_swing_low:
            swings.append({
                "index": i,
                "price": low,
                "type": "low"
            })

    return swings


# =========================
# Structure Classification
# =========================

def classify_structure(swings: List[Dict]) -> List[Dict]:
    """
    Label swings as:
    HH, HL, LH, LL
    """

    labeled = []
    last_high = None
    last_low = None

    for s in swings:
        label = None

        if s["type"] == "high":
            if last_high is None:
                label = "H"
            elif s["price"] > last_high:
                label = "HH"
            else:
                label = "LH"
            last_high = s["price"]

        elif s["type"] == "low":
            if last_low is None:
                label = "L"
            elif s["price"] > last_low:
                label = "HL"
            else:
                label = "LL"
            last_low = s["price"]

        labeled.append({
            **s,
            "label": label
        })

    return labeled


# =========================
# Trend Detection
# =========================

def detect_trend(labeled_swings: List[Dict]) -> str:
    """
    Determine market trend based on last structure.
    """

    labels = [s["label"] for s in labeled_swings if s["label"]]

    if labels[-4:].count("HH") >= 1 and labels[-4:].count("HL") >= 1:
        return "UPTREND"

    if labels[-4:].count("LL") >= 1 and labels[-4:].count("LH") >= 1:
        return "DOWNTREND"

    return "RANGE"
