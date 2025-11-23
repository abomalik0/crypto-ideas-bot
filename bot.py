import os
import re
import logging
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ContextTypes, filters
)

# ------------------------------------
# Logging
# ------------------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ------------------------------------
# Environment Variables
# ------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("❌ ERROR: BOT_TOKEN is missing!")

KOYEB_APP_NAME = os.getenv("KOYEB_APP_NAME", "")
WEBHOOK_URL = f"https://{KOYEB_APP_NAME}.koyeb.app/webhook"

# ------------------------------------
# TradingView Ideas Scraper
# ------------------------------------
def fetch_ideas(symbol: str):
    url = f"https://www.tradingview.com/symbols/{symbol}/ideas/"
    log.info(f"Fetching ideas page: {url}")

    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code != 200:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    cards = soup.select("div.tv-widget-idea")
    ideas = []

    for card in cards[:20]:
        title = card.select_one(".tv-widget-idea__title")
        img = card.select_one("img")
        link = card.select_one("a.js-userlink-popup-anchor")

        ideas.append({
            "title": title.text.strip() if title else "Untitled",
            "image": img["src"] if img else None,
            "link": "https://www.tradingview.com" + link["href"] if link else ""
        })

    return ideas

# ------------------------------------
# Commands
# ------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك! 👋\n\n"
        "/ideas BTCUSDT\n"
        "/ideas ETHUSDT\n"
        "/GOLD\n"
        "/BTCUSDT\n"
    )

async def ideas_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("⚠️ استخدم: /ideas BTCUSDT")
        return

    symbol = context.args[0].upper()
    await update.message.reply_text(f"⏳ جاري جلب أحدث الأفكار لـ {symbol} ...")

    ideas = fetch_ideas(symbol)
    if not ideas:
        await update.message.reply_text(f"⚠️ لا توجد أفكار متاحة الآن لـ {symbol}.")
        return

    for idea in ideas:
        caption = f"📌 {idea['title']}\n🔗 {idea['link']}"
        await update.message.reply_photo(idea["image"], caption=caption)

async def direct_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = update.message.text.replace("/", "").upper()

    if not re.match(r"^[A-Z0-9]{3,10}$", symbol):
        return

    context.args = [symbol]
    await ideas_handler(update, context)

# ------------------------------------
# MAIN (Webhook only)
# ------------------------------------
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^/"), direct_symbol))

    # --- Start webhook ----
    await app.bot.set_webhook(WEBHOOK_URL)
    log.info(f"🚀 Webhook started: {WEBHOOK_URL}")

    await app.run_webhook(
        listen="0.0.0.0",
        port=8080,
        url_path="webhook",
        webhook_url=WEBHOOK_URL
    )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
