def backtest_harmonic_patterns(patterns, candles):
    results = []

    for p in patterns:
        status = p["status"]
        direction = p["direction"]

        # Entry
        entry = sum(p["prz"]) / 2

        # TP / SL logic
        if status == "completed":
            tp = p["targets"][0]
            sl = p["stop_loss"]
        else:
            # سلوك سعري فقط
            rr = abs(p["prz"][1] - p["prz"][0])
            if direction == "BUY":
                tp = entry + rr
                sl = entry - rr
            else:
                tp = entry - rr
                sl = entry + rr

        hit_tp = False
        hit_sl = False
        candles_to_hit = 0

        for i, c in enumerate(candles):
            high = c["high"]
            low = c["low"]

            if direction == "BUY":
                if low <= sl:
                    hit_sl = True
                    candles_to_hit = i
                    break
                if high >= tp:
                    hit_tp = True
                    candles_to_hit = i
                    break
            else:
                if high >= sl:
                    hit_sl = True
                    candles_to_hit = i
                    break
                if low <= tp:
                    hit_tp = True
                    candles_to_hit = i
                    break

        results.append({
            "pattern": p["pattern"],
            "status": status,
            "direction": direction,
            "result": "WIN" if hit_tp else "LOSS" if hit_sl else "OPEN",
            "candles_to_hit": candles_to_hit if hit_tp or hit_sl else None
        })

    return results
