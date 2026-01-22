def detect_swings(candles, lookback=3, min_move=0.003):
    """
    Professional swing detector (Harmonic-ready)
    - Uses HIGH / LOW (not close)
    - Enforces alternation (HLHL)
    - Filters noise
    """

    swings = []

    highs = [c["high"] for c in candles]
    lows  = [c["low"] for c in candles]

    last_type = None  # "high" or "low"

    for i in range(lookback, len(candles) - lookback):

        # ---------- Detect swing high ----------
        is_high = all(
            highs[i] > highs[i - j] and highs[i] > highs[i + j]
            for j in range(1, lookback + 1)
        )

        # ---------- Detect swing low ----------
        is_low = all(
            lows[i] < lows[i - j] and lows[i] < lows[i + j]
            for j in range(1, lookback + 1)
        )

        # ---------- Process swing high ----------
        if is_high and last_type != "high":
            price = highs[i]

            if not swings:
                swings.append(price)
                last_type = "high"
            else:
                move = abs(price - swings[-1]) / swings[-1]
                if move >= min_move:
                    swings.append(price)
                    last_type = "high"

        # ---------- Process swing low ----------
        elif is_low and last_type != "low":
            price = lows[i]

            if not swings:
                swings.append(price)
                last_type = "low"
            else:
                move = abs(price - swings[-1]) / swings[-1]
                if move >= min_move:
                    swings.append(price)
                    last_type = "low"

    return swings
