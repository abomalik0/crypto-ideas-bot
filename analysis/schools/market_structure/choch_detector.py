# analysis/schools/market_structure/choch_detector.py

from typing import List, Dict


def detect_choch(
    swings: List[Dict],
    bos_events: List[Dict]
) -> List[Dict]:
    """
    Detect Change Of Character (CHoCH)

    swings format:
    {
        "index": int,
        "price": float,
        "type": "high" | "low"
    }

    bos_events format:
    {
        "type": "BOS",
        "direction": "bullish" | "bearish",
        "break_price": float,
        "swing_index": int
    }

    Returns:
    [
        {
            "type": "CHoCH",
            "direction": "bullish" | "bearish",
            "break_price": float,
            "swing_index": int
        }
    ]
    """

    choch_events = []

    if not swings or not bos_events:
        return choch_events

    # =====================
    # Determine last trend from BOS
    # =====================
    last_bos = bos_events[-1]
    trend = last_bos["direction"]

    last_hl = None
    last_lh = None

    for s in swings:
        # =====================
        # Track internal structure
        # =====================
        if s["type"] == "low":
            last_hl = s

        elif s["type"] == "high":
            last_lh = s

        # =====================
        # CHoCH Logic
        # =====================
        if trend == "bullish" and last_hl:
            # Bullish → break last HL = bearish CHoCH
            if s["type"] == "low" and s["price"] < last_hl["price"]:
                choch_events.append({
                    "type": "CHoCH",
                    "direction": "bearish",
                    "break_price": s["price"],
                    "swing_index": s["index"],
                })
                break

        elif trend == "bearish" and last_lh:
            # Bearish → break last LH = bullish CHoCH
            if s["type"] == "high" and s["price"] > last_lh["price"]:
                choch_events.append({
                    "type": "CHoCH",
                    "direction": "bullish",
                    "break_price": s["price"],
                    "swing_index": s["index"],
                })
                break

    return choch_events
