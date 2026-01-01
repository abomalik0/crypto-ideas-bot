"""
HARMONIC SCANNER
================

• Scan multiple swing windows
• Detect forming, confirmed & completed harmonic patterns
• Rank patterns by confidence
• Relaxed logic for backtesting & discovery
"""

from typing import List, Dict, Any
from .harmonic_engine import analyze_harmonic


# =========================
# Thresholds (RELAXED)
# =========================

FORMING_THRESHOLD = 20       # كان 30 → أخف
CONFIRMED_THRESHOLD = 45     # كان 55
COMPLETED_THRESHOLD = 70     # كان 80


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
        d_index = i + 4

        # Analyze harmonic structure
        result = analyze_harmonic(
            symbol=symbol,
            timeframe=timeframe,
            swings=subset,
        )

        if not result:
            continue

        if not result.get("pattern"):
            continue

        confidence = float(result.get("confidence", 0.0))

        # =========================
        # Status by Confidence
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
        # Direction Logic (FIXED)
        # =========================
        # Harmonic logic:
        # Last leg down → BUY
        # Last leg up   → SELL
        direction = "BUY" if subset[-1] < subset[-2] else "SELL"

        # =========================
        # Confirmation Logic
        # =========================
        point_c = subset[3]
        point_d = subset[4]

        confirmed = False
        if direction == "BUY" and point_d <= point_c:
            confirmed = True
        elif direction == "SELL" and point_d >= point_c:
            confirmed = True

        # Upgrade forming → confirmed
        if confirmed and status == "forming":
            status = "confirmed"

        # =========================
        # Targets / SL
        # =========================
        targets = []
        stop_loss = None

        if status in ("confirmed", "completed"):
            targets = result.get("targets", [])
            stop_loss = result.get("stop_loss")

        # =========================
        # Store Pattern
        # =========================
        patterns.append({
            "pattern": result.get("pattern"),
            "direction": direction,
            "confidence": confidence,
            "status": status,
            "confirmed": confirmed,
            "prz": result.get("prz"),
            "point_c": point_c,
            "point_d": point_d,
            "d_index": d_index,
            "targets": targets,
            "stop_loss": stop_loss,
        })

    # =========================
    # Sort strongest first
    # =========================
    patterns.sort(key=lambda x: x["confidence"], reverse=True)

    return patterns
