import aiohttp
import asyncio

TV_API = "https://www.tradingview.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://www.tradingview.com",
}


async def fetch_json(url):
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        try:
            async with session.get(url, timeout=10) as r:
                if r.status == 200:
                    return await r.json()
        except:
            return None
    return None


async def get_ideas(symbol, limit=20):
    url = f"{TV_API}/ideas-page/?symbol={symbol.upper()}&limit={limit}"

    data = await fetch_json(url)
    if not data or "ideas" not in data:
        return []

    ideas = []
    for idea in data["ideas"]:
        ideas.append({
            "title": idea.get("title", "TradingView Idea"),
            "image": idea.get("thumb_url", None),
            "link": TV_API + idea.get("public_id", ""),
        })

    return ideas
