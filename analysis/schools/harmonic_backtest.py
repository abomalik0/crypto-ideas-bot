def backtest_harmonic_patterns(patterns, candles):
    results = []

    for p in patterns:

        # نختبر النماذج المكتملة فقط
        if p.get("status") != "completed":
            continue

        # حماية
        if "d_index" not in p:
            continue

        d_index = p["d_index"]

        # ندخل من منتصف PRZ
        entry = sum(p["prz"]) / 2
        tp = p["targets"][0] if p.get("targets") else None
        sl = p.get("stop_loss")

        if tp is None or sl is None:
            continue

        hit_tp = False
        hit_sl = False

        # =========================
        # نبدأ الباكتيست بعد شمعة D فقط
        # =========================
        future_candles = candles[d_index + 1:]

        for c in future_candles:
            high = c["high"]
            low = c["low"]

            # ===== BUY =====
            if p["direction"] == "BUY":
                if low <= sl:
                    hit_sl = True
                    break
                if high >= tp:
                    hit_tp = True
                    break

            # ===== SELL =====
            elif p["direction"] == "SELL":
                if high >= sl:
                    hit_sl = True
                    break
                if low <= tp:
                    hit_tp = True
                    break

        results.append({
            "pattern": p["pattern"],
            "direction": p["direction"],
            "entry": entry,
            "tp": tp,
            "sl": sl,
            "result": "WIN" if hit_tp else "LOSS" if hit_sl else "OPEN"
        })

    return results
