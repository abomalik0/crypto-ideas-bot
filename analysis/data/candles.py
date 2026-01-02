import csv
import os


def get_historical_candles(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 500
):
    """
    Load historical candles from CSV ONLY.
    No Binance. No API. No pagination.

    Required CSV format:
    open,high,low,close
    """

    csv_path = f"data/{symbol}_{timeframe}.csv"

    if not os.path.exists(csv_path):
        print(f"❌ CSV file not found: {csv_path}")
        return []

    candles = []

    try:
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)

            for row in reader:
                candles.append({
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                })

    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return []

    if not candles:
        print("❌ CSV file is empty")
        return []

    # ✂️ Trim to limit (from the END = latest candles)
    candles = candles[-limit:]

    print(f"📁 Loaded {len(candles)} candles from CSV")

    return candles
