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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CryptoIdeasBot/1.0)",
    "Accept": "application/json",
}


def get_historical_candles(symbol: str, timeframe: str = "1h", limit: int = 500):
    """
    Fetch historical candles from Binance.
    Returns list of dicts: open, high, low, close
    """

    interval = TF_MAP.get(timeframe)
    if not interval:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "limit": min(limit, 1000),
    }

    try:
        response = requests.get(
            BINANCE_URL,
            params=params,
            headers=HEADERS,
            timeout=15
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
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

    return candles
