import os
import logging
import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# TradingView FEED
TV_URL = "https://www.tradingview.com/ideas/{symbol}/rss/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}


# Fetch Ideas
async def fetch_ideas(symbol: str):
    url = TV_URL.format(symbol=symbol)
    ideas = []

    try:
        async with httpx.AsyncClient(timeout=10, headers=HEADERS) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.text
    except Exception as e:
        logger.error(f"Error fetching RSS: {e}")
        return []

    # Parse RSS manually
    items = content.split("<item>")[1:]  # skip RSS header
    for item in items[:10]:  # limit 10 ideas
        try:
            title = item.split("<title><![CDATA[")[1].split("]]></title>")[0]
            link = item.split("<link><![CDATA[")[1].split("]]></link>")[0]
            ideas.append((title, link))
        except:
            continue

    return ideas


# /start Message
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 أهلاً!\n"
        "هذا البوت يجلب لك آخر أفكار TradingView لأي زوج كريبتو.\n\n"
        "استخدم:\n"
        "/ideas BTCUSDT\n"
        "أو اكتب مباشرة:\n"
        "/BTCUSDT\n\n"
        "سيتم إرسال حتى 10 أفكار في رسائل منفصلة."
    )
    await update.message.reply_text(msg)


# /ideas SYMBOL
async def ideas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        return await update.message.reply_text("❌ مثال صحيح: /ideas BTCUSDT")

    symbol = context.args[0].upper()
    await send_ideas(update, symbol)


# أي أمر يدخل مثل /BTCUSDT
async def symbol_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = update.message.text.replace("/", "").upper()
    await send_ideas(update, symbol)


# Send Ideas
async def send_ideas(update: Update, symbol: str):
    await update.message.reply_text(f"⏳ جاري جلب أفكار {symbol} من TradingView...")

    ideas = await fetch_ideas(symbol)

    if not ideas:
        return await update.message.reply_text("❌ لا يوجد أفكار لهذا الزوج أو حدث خطأ.")

    for title, link in ideas:
        await update.message.reply_text(
            f"📌 *{title}*\n🔗 {link}",
            parse_mode="Markdown"
        )


# MAIN
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("❌ BOT_TOKEN not set in environment variables!")

    app = Application.builder().token(token).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas_command))

    # Very important: handles any "/BTCUSDT" style command
    app.add_handler(MessageHandler(filters.COMMAND, symbol_command))

    logger.info("Bot running in POLLING mode...")
    app.run_polling()


if __name__ == "__main__":
    main()
