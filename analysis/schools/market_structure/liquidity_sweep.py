# analysis/schools/market_structure/liquidity_sweep.py

from typing import List, Dict


def detect_liquidity_sweep(
    candles: List[Dict],
    swings: List[Dict],
    lookahead: int = 3
) -> List[Dict]:
    """
    Detect Liquidity Sweeps

    candle format:
    {
        "open": float,
        "high": float,
        "low": float,
        "close": float
    }

    swing format:
    {
        "index": int,
        "price": float,
        "type": "high" | "low"
    }

    Returns:
    [
        {
            "type": "LiquiditySweep",
            "direction": "bullish" | "bearish",
            "sweep_price": float,
            "swing_index": int,
            "candle_index": int
        }
    ]
    """

    sweeps = []

    for s in swings:
        idx = s["index"]
        price = s["price"]

        if idx + lookahead >= len(candles):
            continue

        for i in range(idx + 1, idx + lookahead + 1):
            c = candles[i]

            # =====================
            # Bearish Liquidity Sweep (above highs)
            # =====================
            if s["type"] == "high":
                if c["high"] > price and c["close"] < price:
                    sweeps.append({
                        "type": "LiquiditySweep",
                        "direction": "bearish",
                        "sweep_price": c["high"],
                        "swing_index": idx,
                        "candle_index": i,
                    })
                    break

            # =====================
            # Bullish Liquidity Sweep (below lows)
            # =====================
            elif s["type"] == "low":
                if c["low"] < price and c["close"] > price:
                    sweeps.append({
                        "type": "LiquiditySweep",
                        "direction": "bullish",
                        "sweep_price": c["low"],
                        "swing_index": idx,
                        "candle_index": i,
                    })
                    break

    return sweeps
