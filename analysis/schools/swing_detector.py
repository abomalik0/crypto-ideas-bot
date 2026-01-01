# analysis/swing_detector.py

from typing import List, Dict

def detect_swings(candles: List[Dict], lookback: int = 3) -> List[float]:
    """
    Detect swing highs & lows
    Returns list of prices [X, A, B, C, D]
    """

    swings = []

    for i in range(lookback, len(candles) - lookback):
        high = candles[i]["high"]
        low = candles[i]["low"]

        is_swing_high = all(
            high > candles[i - j]["high"] and high > candles[i + j]["high"]
            for j in range(1, lookback + 1)
        )

        is_swing_low = all(
            low < candles[i - j]["low"] and low < candles[i + j]["low"]
            for j in range(1, lookback + 1)
        )

        if is_swing_high:
            swings.append(high)

        elif is_swing_low:
            swings.append(low)

    return swings[-5:]
