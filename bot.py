import os
import requests
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ========================
# 🔑 ENV VARIABLES
# ========================
TOKEN = os.getenv("BOT_TOKEN")
APP_NAME = os.getenv("KOYEB_APP_NAME")

if not TOKEN:
    raise Exception("❌ ERROR: BOT_TOKEN missing!")

if not APP_NAME:
    raise Exception("❌ ERROR: KOYEB_APP_NAME missing!")


# ========================
# TradingView Hidden API
# ========================
API_URL = "https://www.tradingview.com/ideas-page/?symbol={symbol}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}


def get_tv_ideas(symbol):
    url = API_URL.format(symbol=symbol.upper())

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
    except:
        return []

    ideas = []
    for i in data.get("ideas", []):
        idea = {
            "title": i.get("headline", "No title"),
            "author": i.get("author", {}).get("username", "Unknown"),
            "image": i.get("thumb_url"),
            "url": f"https://www.tradingview.com{i.get('public_id','')}",
            "published": datetime.fromtimestamp(i.get("published_datetime", 0)).strftime("%Y-%m-%d %H:%M")
        }
        ideas.append(idea)

    return ideas


# ========================
# Commands
# ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome!\nSend /ideas BTCUSDT to get TradingView ideas."
    )


async def ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("⚠️ Use:\n/ideas BTCUSDT")
        return

    symbol = context.args[0].upper()
    await update.message.reply_text(f"⏳ Fetching ideas for *{symbol}* ...", parse_mode="Markdown")

    results = get_tv_ideas(symbol)

    if not results:
        await update.message.reply_text(
            f"⚠️ No ideas available right now for {symbol}."
        )
        return

    for idea in results[:3]:
        caption = (
            f"🔥 *{idea['title']}*\n"
            f"✍️ Author: {idea['author']}\n"
            f"🕒 {idea['published']}\n"
            f"🔗 {idea['url']}"
        )

        if idea["image"]:
            await update.message.reply_photo(idea["image"], caption=caption, parse_mode="Markdown")
        else:
            await update.message.reply_markdown(caption)


# ========================
# 🚀 Webhook Start (NO asyncio.run)
# ========================
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas))

    print("🚀 Webhook running on port 8080...")

    await app.run_webhook(
        listen="0.0.0.0",
        port=8080,
        url_path=TOKEN,
        webhook_url=f"https://{APP_NAME}.koyeb.app/{TOKEN}"
    )


# ========================
# Correct Event Loop for Koyeb
# ========================
import asyncio

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(main())
    loop.run_forever()
