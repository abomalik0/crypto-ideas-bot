def detect_swings(candles, lookback=3, min_move=0.002):
    """
    Strong swing detector (professional style)
    - lookback: عدد الشموع يمين وشمال
    - min_move: أقل حركة (0.2%)
    """

    swings = []

    for i in range(lookback, len(candles) - lookback):
        high = candles[i]["high"]
        low = candles[i]["low"]

        is_high = all(
            high > candles[i - j]["high"] for j in range(1, lookback + 1)
        ) and all(
            high > candles[i + j]["high"] for j in range(1, lookback + 1)
        )

        is_low = all(
            low < candles[i - j]["low"] for j in range(1, lookback + 1)
        ) and all(
            low < candles[i + j]["low"] for j in range(1, lookback + 1)
        )

        if is_high or is_low:
            value = high if is_high else low

            if not swings:
                swings.append(value)
            else:
                last = swings[-1]
                move = abs(value - last) / last

                if move >= min_move:
                    swings.append(value)

    return swings
