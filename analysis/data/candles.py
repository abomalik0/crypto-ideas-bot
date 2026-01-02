import csv
import os


def get_historical_candles(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 500
):
    """
    CSV ONLY – NO BINANCE – NO API
    """

    csv_path = f"data/{symbol}_{timeframe}.csv"

    if not os.path.exists(csv_path):
        print(f"❌ CSV file not found: {csv_path}")
        return []

    candles = []

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            candles.append({
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            })

    if not candles:
        print("❌ CSV file is empty")
        return []

    candles = candles[-limit:]

    print(f"📁 Loaded {len(candles)} candles from CSV")

    return candles
