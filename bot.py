import requests
from datetime import datetime

def fetch_symbol_ideas(symbol: str, limit: int = 20):
    """
    جلب أفكار TradingView باستخدام API الداخلي (مثل بوت Chart Ideas)
    """
    symbol = symbol.upper()
    url = f"https://www.tradingview.com/ideas-page/?symbol={symbol}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123 Safari/537.36"
        )
    }

    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print("API error:", e)
        return []

    ideas = []

    for i in data.get("ideas", [])[:limit]:
        try:
            idea = {
                "title": i.get("headline") or "No title",
                "author": i.get("author", {}).get("username", ""),
                "image": i.get("thumb_url", ""),
                "published_raw": i.get("published_datetime", ""),
                "url": "https://www.tradingview.com" + i.get("public_id", ""),
            }

            # تحويل الوقت لتنسيق datetime
            if idea["published_raw"]:
                try:
                    idea["published_dt"] = datetime.fromtimestamp(
                        idea["published_raw"]
                    )
                except:
                    idea["published_dt"] = None

            ideas.append(idea)

        except Exception:
            continue

    return ideas
