import csv
import os
import requests

BINANCE_URL = "https://api.binance.com/api/v3/klines"

TF_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}


def get_historical_candles(symbol: str, timeframe: str = "1h", limit: int = 2000):
    """
    Priority:
    1) Load from CSV if exists AND large enough
    2) Fallback to Binance API
    """

    MIN_CSV_SIZE = 300  # أقل عدد شموع مقبول للهارمونيك

    # =====================
    # 1️⃣ Try CSV first
    # =====================
    csv_path = f"data/{symbol}_{timeframe}.csv"

    if os.path.exists(csv_path):
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

        if len(candles) >= MIN_CSV_SIZE:
            print(f"📁 Loaded {len(candles)} candles from CSV")
            return candles
        else:
            print(
                f"⚠️ CSV too small ({len(candles)} candles) "
                f"→ switching to Binance"
            )

    # =====================
    # 2️⃣ Fallback Binance
    # =====================
    interval = TF_MAP.get(timeframe)
    if not interval:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }

    try:
        response = requests.get(BINANCE_URL, params=params, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"❌ Binance API error: {e}")
        return []

    data = response.json()

    candles = []
    for c in data:
        candles.append({
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
        })

    print(f"🌐 Loaded {len(candles)} candles from Binance")
    return candles
