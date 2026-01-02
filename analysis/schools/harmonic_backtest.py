"""
HARMONIC BACKTEST ENGINE
=======================

• Walk-forward backtest (after point D only)
• Entry from PRZ
• Uses real TP / SL for completed patterns
• Uses simplified RR for forming / confirmed
• No repainting – realistic execution
"""

from typing import List, Dict, Any


def backtest_harmonic_patterns(
    patterns: List[Dict[str, Any]],
    candles: List[Dict[str, float]],
) -> List[Dict[str, Any]]:

    results = []

    if not patterns or not candles:
        return results

    for p in patterns:
        status = p.get("status")
        direction = p.get("direction")
        d_index = p.get("d_index")

        # =====================
        # Safety checks
        # =====================
        if d_index is None or d_index >= len(candles) - 1:
            continue

        if "prz" not in p or not p["prz"]:
            continue

        # =====================
        # Entry from PRZ
        # =====================
        prz_low, prz_high = p["prz"]
        entry = (prz_low + prz_high) / 2

        # =====================
        # TP / SL Logic
        # =====================
        if (
            status == "completed"
            and p.get("targets")
            and p.get("stop_loss")
        ):
            # 🎯 حقيقي من الهارمونيك
            tp = p["targets"][0]     # Target 1 فقط
            sl = p["stop_loss"]
        else:
            # 🧪 RR مبسط للاختبار
            rr = abs(prz_high - prz_low)
            if direction == "BUY":
                tp = entry + rr
                sl = entry - rr
            else:  # SELL
                tp = entry - rr
                sl = entry + rr

        hit_tp = False
        hit_sl = False
        candles_to_hit = None

        # =====================
        # Walk Forward (AFTER D)
        # =====================
        for i in range(d_index + 1, len(candles)):
            c = candles[i]
            high = c["high"]
            low = c["low"]

            if direction == "BUY":
                if low <= sl:
                    hit_sl = True
                    candles_to_hit = i - d_index
                    break
                if high >= tp:
                    hit_tp = True
                    candles_to_hit = i - d_index
                    break
            else:  # SELL
                if high >= sl:
                    hit_sl = True
                    candles_to_hit = i - d_index
                    break
                if low <= tp:
                    hit_tp = True
                    candles_to_hit = i - d_index
                    break

        # =====================
        # Final Result
        # =====================
        if hit_tp:
            result = "WIN"
        elif hit_sl:
            result = "LOSS"
        else:
            result = "OPEN"

        results.append({
            "pattern": p.get("pattern"),
            "status": status,
            "direction": direction,
            "entry": round(entry, 2),
            "tp": round(tp, 2),
            "sl": round(sl, 2),
            "result": result,
            "candles_to_hit": candles_to_hit,
            "confidence": round(p.get("confidence", 0), 1),
        })

    return results
