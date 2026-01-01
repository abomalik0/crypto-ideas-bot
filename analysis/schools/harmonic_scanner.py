"""
HARMONIC SCANNER
================

• Scan multiple swing windows
• Detect forming, confirmed & completed harmonic patterns
• Rank patterns by confidence
• Pure harmonic logic (no SMC / ICT)
"""

from typing import List, Dict, Any
from .harmonic_engine import analyze_harmonic


# =========================
# Thresholds
# =========================

FORMING_THRESHOLD = 30      # Minimum confidence to show forming pattern
CONFIRMED_THRESHOLD = 55    # Confirmed harmonic
COMPLETED_THRESHOLD = 80    # Completed harmonic


# =========================
# Main Scanner
# =========================

def scan_harmonic_patterns(
    symbol: str,
    timeframe: str,
    swings: List[float],
) -> List[Dict[str, Any]]:
    """
    Scan all possible 5-swing combinations
    and return detected harmonic patterns.

    Output:
    [
        {
            pattern: str,
            direction: BUY | SELL,
            confidence: float,
            status: forming | confirmed | completed,
            confirmed: bool,
            prz: (low, high),
            point_c: float,
            point_d: float,
            targets: list,
            stop_loss: float | None
        }
    ]
    """

    patterns: List[Dict[str, Any]] = []

    # =========================
    # Safety Check
    # =========================
    if not isinstance(swings, list) or len(swings) < 5:
        return patterns

    # =========================
    # Loop on swing windows
    # =========================
    for i in range(len(swings) - 4):
        subset = swings[i:i + 5]

        # Analyze harmonic structure
        result = analyze_harmonic(
            symbol=symbol,
            timeframe=timeframe,
            swings=subset,
        )

        if not result or not result.get("valid"):
            continue

        confidence = float(result.get("confidence", 0.0))

        # =========================
        # Base Status by Confidence
        # =========================
        if confidence >= COMPLETED_THRESHOLD:
            status = "completed"
        elif confidence >= CONFIRMED_THRESHOLD:
            status = "confirmed"
        elif confidence >= FORMING_THRESHOLD:
            status = "forming"
        else:
            continue

        # =========================
        # Direction Logic
        # =========================
        # D < C → BUY
        # D > C → SELL
        direction = "BUY" if subset[-1] < subset[-2] else "SELL"

        # =========================
        # Confirmation Logic
        # =========================
        point_c = subset[3]
        point_d = subset[4]
        confirmed = False

        if direction == "BUY" and point_d > point_c:
            confirmed = True
        elif direction == "SELL" and point_d < point_c:
            confirmed = True

        # Upgrade forming → confirmed if price confirms
        if confirmed and status == "forming":
            status = "confirmed"

        # =========================
        # Store Pattern
        # =========================
        pattern_data = {
            "pattern": result.get("pattern"),
            "direction": direction,
            "confidence": confidence,
            "status": status,
            "confirmed": confirmed,
            "prz": result.get("prz"),
            "point_c": point_c,
            "point_d": point_d,
            "targets": result.get("targets", []) if status == "completed" else [],
            "stop_loss": result.get("stop_loss") if status == "completed" else None,
        }

        patterns.append(pattern_data)

    # =========================
    # Sort strongest first
    # =========================
    patterns.sort(key=lambda x: x["confidence"], reverse=True)

    return patterns
