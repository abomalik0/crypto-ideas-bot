"""
MARKET STRUCTURE – SCANNER
==========================

• Uses structure_engine
• Prints market structure summary
"""

from typing import List, Dict

from .structure_engine import (
    detect_structure_swings,
    classify_structure,
    detect_trend,
)


def scan_market_structure(candles: List[Dict]) -> Dict:
    """
    Main scanner entry point
    """

    swings = detect_structure_swings(candles)

    if len(swings) < 4:
        return {
            "valid": False,
            "reason": "Not enough swings"
        }

    labeled = classify_structure(swings)
    trend = detect_trend(labeled)

    return {
        "valid": True,
        "trend": trend,
        "last_structure": labeled[-4:],  # آخر هيكل واضح
        "total_swings": len(labeled),
    }
