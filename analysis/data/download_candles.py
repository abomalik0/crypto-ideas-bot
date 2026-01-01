# analysis/data/download_candles.py

import csv
import time
import requests
import os

BINANCE_URL = "https://api.binance.com/api/v3/klines"

TF_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}


def download_candles(
    symbol="BTCUSDT",
    timeframe="1h",
    total=2000,
    out_dir="data"
):
    interval = TF_MAP.get(timeframe)
    if not interval:
        raise ValueError("Unsupported timeframe")

    os.makedirs(out_dir, exist_ok=True)

    all_candles = []
    limit = 1000
    end_time = None

    print(f"⬇️ Downloading {total} candles for {symbol} ({timeframe})")

    while len(all_candles) < total:
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }

        if end_time:
            params["endTime"] = end_time

        r = requests.get(BINANCE_URL, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        if not data:
            break

        all_candles = data + all_candles
        end_time = data[0][0] - 1

        print(f"📊 Loaded: {len(all_candles)}")
        time.sleep(0.3)

    candles = all_candles[-total:]

    csv_path = f"{out_dir}/{symbol}_{timeframe}.csv"

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])

        for c in candles:
            writer.writerow([
                int(c[0] / 1000),
                float(c[1]),
                float(c[2]),
                float(c[3]),
                float(c[4]),
                float(c[5]),
            ])

    print(f"\n✅ Saved {len(candles)} candles to {csv_path}")


if __name__ == "__main__":
    download_candles(
        symbol="BTCUSDT",
        timeframe="1h",
        total=2000,
        out_dir="data"
    )
