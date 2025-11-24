import os
import logging
import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# TradingView RSS URL
TV_RSS = "https://www.tradingview.com/ideas/{symbol}/rss/"

headers = {
    "User-Agent": "Mozilla/5.0"
}

async def fetch_ideas(symbol: str):
    """Fetch ideas from TradingView RSS"""
    url = TV_RSS.format(symbol=symbol)

    try:
        async with httpx.AsyncClient(timeout=10, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.text
    except Exception:
        return []

    # Parse RSS manually
    items = content.split("<item>")[1:11]  # Get max 10 ideas
    ideas = []

    for item in items:
        try:
            title = item.split("<title><![CDATA[")[1].split("]]></title>")[0]
            link = item.split("<link><![CDATA[")[1].split("]]></link>")[0]
            ideas.append((title, link))
        except:
            continue

    return ideas

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 أهلاً!\n"
        "هذا البوت يجلب آخر أفكار TradingView لأي زوج.\n\n"
        "استخدم:\n"
        "/ideas BTCUSDT\n"
        "أو:\n"
        "/BTCUSDT\n"
    )
    await update.message.reply_text(msg)

async def ideas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ استخدم: /ideas BTCUSDT")
        return
    
    symbol = context.args[0].upper()
    await send_ideas(update, symbol)

async def symbol_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = update.message.text.replace("/", "").upper()
    await send_ideas(update, symbol)

async def send_ideas(update: Update, symbol: str):
    await update.message.reply_text(f"⏳ جاري جلب أفكار {symbol} من TradingView...")

    ideas = await fetch_ideas(symbol)

    if not ideas:
        await update.message.reply_text("❌ لم يتم العثور على أفكار.")
        return

    for title, link in ideas:
        await update.message.reply_text(f"📌 **{title}**\n🔗 {link}", parse_mode="Markdown")

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("❌ BOT_TOKEN is missing in environment variables!")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas_command))
    app.add_handler(CommandHandler("", symbol_command))

    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
