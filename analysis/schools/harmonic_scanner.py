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

FORMING_THRESHOLD = 30     # Minimum confidence to show forming pattern
COMPLETED_THRESHOLD = 80   # Minimum confidence to mark pattern as completed


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

    Output structure:
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

    # Safety check
    if not isinstance(swings, list) or len(swings) < 5:
        return patterns

    # Loop over all possible 5-swing windows
    for i in range(len(swings) - 4):
        subset = swings[i:i + 5]

        # Analyze harmonic structure
        result = analyze_harmonic(
            symbol=symbol,
            timeframe=timeframe,
            swings=subset,
        )

        # Skip invalid structures
        if not result or not result.get("valid"):
            continue

        confidence = float(result.get("confidence", 0.0))

        # =========================
        # Pattern Status
        # =========================
        if confidence >= COMPLETED_THRESHOLD:
            status = "completed"
        elif confidence >= FORMING_THRESHOLD:
            status = "forming"
        else:
            # أقل من كده → لسه محاولة تكوين
            status = "forming"

        # =========================
        # Direction Logic
        # =========================
        direction = "BUY" if subset[-1] < subset[-2] else "SELL"

        # =========================
        # Store Result
        # =========================
        patterns.append({
            "pattern": result.get("pattern"),
            "direction": direction,
            "confidence": confidence,
            "status": status,
            "prz": result.get("prz"),
            "targets": result.get("targets", []) if status == "completed" else [],
            "stop_loss": result.get("stop_loss") if status == "completed" else None,
        })

    # =========================
    # Sort strongest first
    # =========================
    patterns.sort(key=lambda x: x["confidence"], reverse=True)

    return patterns
