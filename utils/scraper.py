import requests

BASE_URL = "https://scanner.tradingview.com/crypto/scan"

def get_tv_ideas(symbol: str):
    if symbol.endswith("USDT"):
        search_pair = symbol.replace("USDT", "USD")
    else:
        search_pair = symbol

    payload = {
        "symbols": {
            "tickers": [f"BINANCE:{search_pair}"]
        },
        "query": {"types": []},
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
        ideas_raw = item.get("d")[2]

        if not ideas_raw:
            return []

        ideas = []
        for idea in ideas_raw:
            ideas.append({
                "title": idea.get("title", "No title"),
                "link": f"https://www.tradingview.com{idea.get('link', '')}"
            })

        return ideas[:10]

    except Exception as e:
        print("TradingView API Error:", e)
        return []
