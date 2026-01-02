import csv
import os
import time
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

# ✅ Headers مهمة لتفادي 451 على GitHub Actions
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; HarmonicBot/1.0)",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_historical_candles(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 500
):
    """
    Load historical candles with:
    1) CSV priority
    2) Binance API pagination (max 1000 / request)
    """

    MAX_PER_REQUEST = 1000

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

        if len(candles) >= limit:
            print(f"📁 Loaded {len(candles)} candles from CSV")
            return candles[:limit]

        print(f"⚠️ CSV too small ({len(candles)} candles) → switching to Binance")

    # =====================
    # 2️⃣ Binance Pagination
    # =====================
    interval = TF_MAP.get(timeframe)
    if not interval:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    all_candles = []
    end_time = None

    while len(all_candles) < limit:
        fetch_limit = min(MAX_PER_REQUEST, limit - len(all_candles))

        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": fetch_limit,
        }

        if end_time:
            params["endTime"] = end_time

        try:
            r = requests.get(
                BINANCE_URL,
                params=params,
                headers=HEADERS,   # ⭐ الحل هنا
                timeout=10
            )
            r.raise_for_status()
        except Exception as e:
            print(f"❌ Binance API error: {e}")
            break

        data = r.json()
        if not data:
            break

        candles = []
        for c in data:
            candles.append({
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
            })

        # ⏪ بنضيف البيانات القديمة في الأول
        all_candles = candles + all_candles
        end_time = data[0][0] - 1

        time.sleep(0.25)  # Binance safety

    if not all_candles:
        print("❌ No candles loaded from Binance")
        return []

    print(f"🌐 Loaded {len(all_candles)} candles from Binance")

    return all_candles[-limit:]
