# analysis/schools/market_structure/bos_detector.py

from typing import List, Dict


def detect_bos(swings: List[Dict]) -> List[Dict]:
    """
    Detect Break Of Structure (BOS) events.

    swing format:
    {
        "index": int,
        "price": float,
        "type": "high" | "low"
    }

    Returns:
    [
        {
            "type": "BOS",
            "direction": "bullish" | "bearish",
            "break_price": float,
            "swing_index": int
        }
    ]
    """

    bos_events = []

    if not swings or len(swings) < 4:
        return bos_events

    last_high = None
    last_low = None

    for s in swings:
        # =====================
        # Track last structure
        # =====================
        if s["type"] == "high":
            # Bullish BOS: price breaks previous high
            if last_high and s["price"] > last_high["price"]:
                bos_events.append({
                    "type": "BOS",
                    "direction": "bullish",
                    "break_price": s["price"],
                    "swing_index": s["index"],
                })

            last_high = s

        elif s["type"] == "low":
            # Bearish BOS: price breaks previous low
            if last_low and s["price"] < last_low["price"]:
                bos_events.append({
                    "type": "BOS",
                    "direction": "bearish",
                    "break_price": s["price"],
                    "swing_index": s["index"],
                })

            last_low = s

    return bos_events
