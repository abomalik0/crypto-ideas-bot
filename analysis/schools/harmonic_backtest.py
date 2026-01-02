def backtest_harmonic_patterns(patterns, candles):
    results = []

    for p in patterns:
        status = p["status"]
        direction = p["direction"]
        d_index = p.get("d_index", 0)

        # =====================
        # Entry from PRZ
        # =====================
        prz_low, prz_high = p["prz"]
        entry = (prz_low + prz_high) / 2

        # =====================
        # TP / SL
        # =====================
        if status == "completed" and p.get("targets") and p.get("stop_loss"):
            tp = p["targets"][0]   # Target 1 فقط
            sl = p["stop_loss"]
        else:
            # RR مبسط للاختبار
            rr = abs(prz_high - prz_low)
            if direction == "BUY":
                tp = entry + rr
                sl = entry - rr
            else:
                tp = entry - rr
                sl = entry + rr

        hit_tp = False
        hit_sl = False
        candles_to_hit = None

        # =====================
        # Walk forward (بعد D فقط)
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
        # Save Result
        # =====================
        result = "WIN" if hit_tp else "LOSS"

        results.append({
            "pattern": p["pattern"],
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
