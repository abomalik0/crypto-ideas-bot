import os
import re
import logging
import requests
from bs4 import BeautifulSoup
from telegram import Update, InputMediaPhoto
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
    """
    Get up to 20 latest ideas from TradingView chart ideas page.
    New endpoint (better than RSS).
    """
    url = f"https://www.tradingview.com/symbols/{symbol}/ideas/"
    log.info(f"Fetching ideas page: {url}")

    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code != 200:
        log.warning("Bad response from TradingView")
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    # Get idea cards (latest posts)
    cards = soup.select("a.js-userlink-popup-anchor")
    ideas = []

    count = 0
    for card in cards:
        if count >= 20:
            break

        parent = card.find_parent("div", class_="tv-widget-idea")
        if not parent:
            continue

        title_el = parent.select_one(".tv-widget-idea__title")
        img_el = parent.select_one("img")

        title = title_el.text.strip() if title_el else "Untitled"
        img = img_el["src"] if img_el else None
        link = "https://www.tradingview.com" + card["href"]

        ideas.append({
            "title": title,
            "image": img,
            "link": link
        })

        count += 1

    return ideas


# ------------------------------------
# /start Command
# ------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "أهلاً بك! 👋\n\n"
        "📈 هذا البوت يجلب لك أحدث *أفكار وتحليلات TradingView* لأي زوج كريبتو أو عملات أو ذهب.\n\n"
        "📌 الطريقة الأولى (مفضلة):\n"
        "/ideas BTCUSDT\n"
        "/ideas BTCUSD\n"
        "/ideas ETHUSDT\n"
        "/ideas GOLD\n\n"
        "✏️ الطريقة الثانية:\n"
        "اكتب اسم الزوج مباشرة مثل:\n"
        "/BTCUSDT\n"
        "/BTCUSD\n"
        "/GOLD\n\n"
        "سيتم جلب حتى 20 فكرة (إذا كانت موجودة).\n"
    )
    await update.message.reply_text(text)


# ------------------------------------
# /ideas SYMBOL Handler
# ------------------------------------
async def ideas_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("⚠️ استخدم: /ideas BTCUSDT")
        return

    symbol = context.args[0].upper()
    await update.message.reply_text(f"⏳ جاري جلب أحدث الأفكار لـ *{symbol}* ...")

    ideas = fetch_ideas(symbol)
    if not ideas:
        await update.message.reply_text(f"⚠️ لا توجد أفكار متاحة حاليًا لـ *{symbol}*.")
        return

    # Send each idea
    for idea in ideas:
        caption = f"📌 *{idea['title']}*\n🔗 {idea['link']}"
        await update.message.reply_photo(idea["image"], caption=caption, parse_mode="Markdown")


# ------------------------------------
# Handle direct commands like /BTCUSDT
# ------------------------------------
async def direct_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace("/", "").upper()

    if text in ["START", "IDEAS"]:
        return

    if not re.match(r"^[A-Z0-9]{3,10}$", text):
        return

    context.args = [text]
    await ideas_handler(update, context)


# ------------------------------------
# MAIN (Webhook)
# ------------------------------------
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^/"), direct_symbol))

    # Start webhook
    await app.initialize()
    await app.start()
    await app.bot.set_webhook(WEBHOOK_URL)
    log.info(f"🚀 Webhook running: {WEBHOOK_URL}")

    await app.updater.start_polling()  # Needed for Koyeb internal loop
    await app.run_until_disconnected()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
