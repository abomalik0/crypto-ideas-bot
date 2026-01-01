from typing import List, Dict, Any
from .harmonic_engine import analyze_harmonic

FORMING_THRESHOLD = 60   # %
COMPLETED_THRESHOLD = 90 # %

def scan_harmonic_patterns(
    symbol: str,
    timeframe: str,
    swings: List[float],
) -> List[Dict[str, Any]]:

    patterns = []

    # نلف على كل 5 Swings محتملة
    for i in range(len(swings) - 4):
        subset = swings[i:i + 5]

        result = analyze_harmonic(
            symbol=symbol,
            timeframe=timeframe,
            swings=subset,
        )

        if not result.get("valid"):
            continue

        confidence = result.get("confidence", 0)

        if confidence >= COMPLETED_THRESHOLD:
            status = "completed"
        elif confidence >= FORMING_THRESHOLD:
            status = "forming"
        else:
            continue

        patterns.append({
            "pattern": result["pattern"],
            "direction": "BUY" if subset[-1] < subset[-2] else "SELL",
            "confidence": confidence,
            "status": status,
            "prz": result.get("prz"),
            "targets": result.get("targets", []),
            "stop_loss": result.get("stop_loss"),
        })

    # ترتيب من الأقوى للأضعف
    patterns.sort(key=lambda x: x["confidence"], reverse=True)

    return patterns
