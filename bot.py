import os
import logging
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ------------------------------
# CONFIG
# ------------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("❌ BOT_TOKEN is missing!")

APP_NAME = os.getenv("KOYEB_APP_NAME")
if not APP_NAME:
    raise Exception("❌ KOYEB_APP_NAME is missing!")

WEBHOOK_URL = f"https://{APP_NAME}.koyeb.app/webhook"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ------------------------------
# SCRAPER FUNCTION
# ------------------------------

def fetch_ideas(symbol):
    url = f"https://www.tradingview.com/symbols/{symbol}/ideas/"
    logger.info(f"Fetching ideas page for {symbol}: {url}")

    response = requests.get(url)
    if response.status_code != 200:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    ideas = []

    for card in soup.select("div.card-RL30K"):
        title = card.select_one("a[href*='/chart/']")
        if not title:
            continue

        idea_url = "https://www.tradingview.com" + title["href"].split("?")[0]
        text_title = title.get_text(strip=True)

        img_tag = card.select_one("img[src]")
        img_url = img_tag["src"] if img_tag else None

        ideas.append({
            "title": text_title,
            "url": idea_url,
            "image": img_url
        })

        if len(ideas) >= 20:
            break

    return ideas


# ------------------------------
# BOT COMMANDS
# ------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 أهلاً بك!\n"
        "📈 ابعت لي رمز العملة مثل:\n"
        "/ideas BTCUSDT\n"
        "/ideas BTCUSD\n"
        "/ideas GOLD\n\n"
        "أو ببساطة:\n"
        "/BTCUSDT\n"
        "/GOLD\n\n"
        "سأجيبك بأحدث 20 فكرة على TradingView."
    )
    await update.message.reply_text(text)


async def command_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("⚠️ استخدم: /ideas BTCUSDT")
        return

    symbol = context.args[0].upper()
    await update.message.reply_text(f"⌛ جاري جلب الأفكار لـ {symbol} ...")

    ideas = fetch_ideas(symbol)

    if not ideas:
        await update.message.reply_text(f"⚠️ لا توجد أفكار متاحة الآن لـ {symbol}.")
        return

    for idea in ideas:
        msg = f"📌 *{idea['title']}*\n🔗 {idea['url']}"
        await update.message.reply_photo(photo=idea["image"], caption=msg, parse_mode="Markdown")


async def direct_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = update.message.text.replace("/", "").upper()
    await command_ideas(update, context)


# ------------------------------
# MAIN (WEBHOOK ONLY)
# ------------------------------

async def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", command_ideas))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, direct_symbol))

    logger.info("🚀 Setting webhook...")
    await app.bot.set_webhook(WEBHOOK_URL)

    logger.info(f"🔥 Bot is running on Webhook: {WEBHOOK_URL}")

    await app.run_webhook(
        listen="0.0.0.0",
        port=8080,
        webhook_url=WEBHOOK_URL,
    )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
