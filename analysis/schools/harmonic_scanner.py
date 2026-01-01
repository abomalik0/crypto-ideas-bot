"""
HARMONIC SCHOOL – MULTI PATTERN SCANNER
======================================

• Scan ALL possible harmonic patterns
• Works on swing sequences
• Uses core harmonic engine
"""

from typing import List, Dict, Any
from analysis.schools.harmonic_engine import analyze_harmonic


def scan_harmonic_patterns(
    symbol: str,
    timeframe: str,
    swings: List[float],
    min_confidence: float = 60.0,
) -> List[Dict[str, Any]]:
    """
    Scan all possible harmonic patterns from swings list.

    swings: [p1, p2, p3, p4, p5, p6, ...]
    """

    results: List[Dict[str, Any]] = []

    if not swings or len(swings) < 5:
        return results

    # Sliding window scan
    for i in range(len(swings) - 4):
        window = swings[i : i + 5]

        analysis = analyze_harmonic(
            symbol=symbol,
            timeframe=timeframe,
            swings=window,
        )

        if not analysis.get("valid"):
            continue

        confidence = analysis.get("confidence", 0.0)
        if confidence < min_confidence:
            continue

        # Determine pattern direction
        X = analysis["points"]["X"]
        D = analysis["points"]["D"]
        direction = "bullish" if D < X else "bearish"

        analysis["direction"] = direction
        analysis["swing_index"] = i

        results.append(analysis)

    # Sort strongest first
    results.sort(key=lambda x: x.get("confidence", 0), reverse=True)

    return results
