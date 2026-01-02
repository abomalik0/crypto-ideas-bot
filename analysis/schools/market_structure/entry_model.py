# analysis/schools/market_structure/entry_model.py

from typing import List, Dict


def detect_entry_model(
    candles: List[Dict],
    swings: List[Dict],
    choch_events: List[Dict],
    sweeps: List[Dict],
    bos_events: List[Dict],
    rr: float = 2.0
) -> List[Dict]:
    """
    Detect High-Probability Entry Models

    Returns:
    [
        {
            "type": "ENTRY",
            "direction": "bullish" | "bearish",
            "entry_price": float,
            "stop_loss": float,
            "take_profit": float,
            "index": int
        }
    ]
    """

    entries = []

    for sweep in sweeps:
        sweep_idx = sweep["candle_index"]
        direction = sweep["direction"]

        # =====================
        # Match CHoCH after Sweep
        # =====================
        choch_match = next(
            (
                c for c in choch_events
                if c["direction"] == direction
                and c["index"] > sweep_idx
            ),
            None
        )

        if not choch_match:
            continue

        # =====================
        # Match BOS after CHoCH
        # =====================
        bos_match = next(
            (
                b for b in bos_events
                if b["direction"] == direction
                and b["index"] > choch_match["index"]
            ),
            None
        )

        if not bos_match:
            continue

        entry_idx = bos_match["index"]
        entry_candle = candles[entry_idx]

        # =====================
        # Entry / SL / TP
        # =====================
        if direction == "bullish":
            entry_price = entry_candle["close"]
            stop_loss = min(
                c["low"] for c in candles[sweep_idx:entry_idx + 1]
            )
            take_profit = entry_price + (entry_price - stop_loss) * rr
        else:
            entry_price = entry_candle["close"]
            stop_loss = max(
                c["high"] for c in candles[sweep_idx:entry_idx + 1]
            )
            take_profit = entry_price - (stop_loss - entry_price) * rr

        entries.append({
            "type": "ENTRY",
            "direction": direction,
            "entry_price": round(entry_price, 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "index": entry_idx,
        })

    return entries
