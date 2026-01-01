def backtest_harmonic_patterns(patterns, candles):
    results = []

    for p in patterns:
        if p["status"] != "completed":
            continue

        entry = sum(p["prz"]) / 2
        tp = p["targets"][0]
        sl = p["stop_loss"]

        hit_tp = False
        hit_sl = False

        for c in candles:
            high = c["high"]
            low = c["low"]

            if p["direction"] == "bullish":
                if low <= sl:
                    hit_sl = True
                    break
                if high >= tp:
                    hit_tp = True
                    break
            else:
                if high >= sl:
                    hit_sl = True
                    break
                if low <= tp:
                    hit_tp = True
                    break

        results.append({
            "pattern": p["pattern"],
            "direction": p["direction"],
            "result": "WIN" if hit_tp else "LOSS" if hit_sl else "OPEN"
        })

    return results
