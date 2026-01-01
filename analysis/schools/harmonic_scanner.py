"""
HARMONIC SCANNER
================

• Scan multiple swing windows
• Detect completed & forming harmonic patterns
• Rank patterns by confidence
• Pure harmonic logic (no SMC / ICT)
"""

from typing import List, Dict, Any
from .harmonic_engine import analyze_harmonic


# =========================
# Thresholds
# =========================

FORMING_THRESHOLD = 60    # % minimum confidence for forming pattern
COMPLETED_THRESHOLD = 90  # % minimum confidence for completed pattern


# =========================
# Scanner
# =========================

def scan_harmonic_patterns(
    symbol: str,
    timeframe: str,
    swings: List[float],
) -> List[Dict[str, Any]]:
    """
    Scans all possible 5-point swing combinations
    and returns detected harmonic patterns.

    Returns:
    [
        {
            pattern: str,
            direction: BUY | SELL,
            confidence: float,
            status: completed | forming,
            prz: (low, high),
            targets: list,
            stop_loss: float | None
        }
    ]
    """

    patterns: List[Dict[str, Any]] = []

    if not swings or len(swings) < 5:
        return patterns

    # Loop over all possible 5-swing windows
    for i in range(len(swings) - 4):
        subset = swings[i:i + 5]

        result = analyze_harmonic(
            symbol=symbol,
            timeframe=timeframe,
            swings=subset,
        )

        if not result.get("valid"):
            continue

        confidence = float(result.get("confidence", 0.0))

        # Determine status
        if confidence >= COMPLETED_THRESHOLD:
            status = "completed"
        elif confidence >= FORMING_THRESHOLD:
            status = "forming"
        else:
            continue

        # Direction logic (simple & safe)
        direction = "BUY" if subset[-1] < subset[-2] else "SELL"

        patterns.append({
            "pattern": result.get("pattern"),
            "direction": direction,
            "confidence": confidence,
            "status": status,
            "prz": result.get("prz"),
            "targets": result.get("targets", []) if status == "completed" else [],
            "stop_loss": result.get("stop_loss") if status == "completed" else None,
        })

    # Sort strongest first
    patterns.sort(key=lambda x: x["confidence"], reverse=True)

    return patterns
