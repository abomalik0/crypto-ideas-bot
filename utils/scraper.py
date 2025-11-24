import requests

BASE_URL = "https://scanner.tradingview.com/crypto/scan"

def get_tv_ideas(symbol: str):
    """
    Fast TradingView ideas fetch using JSON API (not HTML).
    Returns list of dicts with title + link.
    """

    # Convert BTCUSDT → BTC/USDT format used by TradingView
    if symbol.endswith("USDT"):
        search_pair = symbol.replace("USDT", "USDT")
    else:
        search_pair = symbol

    payload = {
        "symbols": {
            "tickers": [f"BINANCE:{search_pair}"],
            "query": {"types": []}
        },
        "columns": [
            "name",
            "description",
            "relatedIdeas"
        ]
    }

    try:
        response = requests.post(BASE_URL, json=payload, timeout=10)
        data = response.json()

        if "data" not in data or len(data["data"]) == 0:
            return []

        item = data["data"][0]

        # Extract related ideas safely
        ideas_raw = item.get("d")[2]  # relatedIdeas column

        if not ideas_raw:
            return []

        ideas = []
        for idea in ideas_raw:
            ideas.append({
                "title": idea.get("title", "No title"),
                "link": f"https://www.tradingview.com{idea.get('link','')}"
            })

        return ideas[:10]  # limit to 10 ideas

    except Exception as e:
        print("TradingView API Error:", e)
        return []
