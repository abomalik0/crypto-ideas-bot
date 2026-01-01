def detect_swings(candles, lookback=3, min_move=0.002):
    """
    Strong swing detector (professional style)
    - lookback: عدد الشموع يمين وشمال
    - min_move: أقل حركة (0.2%)
    """

    swings = []
    prices = [c["close"] for c in candles]

    for i in range(lookback, len(prices) - lookback):
        high = prices[i]
        low = prices[i]

        is_high = all(high > prices[i - j] for j in range(1, lookback + 1)) and \
                  all(high > prices[i + j] for j in range(1, lookback + 1))

        is_low = all(low < prices[i - j] for j in range(1, lookback + 1)) and \
                 all(low < prices[i + j] for j in range(1, lookback + 1))

        if is_high or is_low:
            if not swings:
                swings.append(high if is_high else low)
            else:
                last = swings[-1]
                move = abs(high - last) / last

                if move >= min_move:
                    swings.append(high if is_high else low)

    return swings
