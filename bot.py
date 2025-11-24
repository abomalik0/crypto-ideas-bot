import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import feedparser
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
APP_URL = os.getenv("APP_URL")  # https://your-app-name.koyeb.app

# -------------------------------------------------
# جلب أفكار TradingView
# -------------------------------------------------
def fetch_ideas(symbol: str):
    url = f"https://www.tradingview.com/ideas/{symbol}/rss/"
    feed = feedparser.parse(url)

    ideas = []
    for entry in feed.entries[:10]:
        title = entry.get("title", "بدون عنوان")
        link = entry.get("link", "")
        ideas.append(f"📌 *{title}*\n🔗 {link}")

    return ideas


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً!\n"
        "اكتب: /ideas BTCUSDT\n"
        "وسيتم إرسال آخر 10 أفكار من TradingView."
    )


async def ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ يرجى كتابة رمز مثل: /ideas BTCUSDT")
        return

    symbol = context.args[0].upper()

    await update.message.reply_text(f"⏳ جاري جلب أفكار {symbol} من TradingView...")

    results = fetch_ideas(symbol)
    if not results:
        await update.message.reply_text("❌ لم يتم العثور على أفكار.")
        return

    for idea in results:
        await update.message.reply_markdown(idea)


# -------------------------------------------------
# تشغيل البوت - Webhook
# -------------------------------------------------
def main():
    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN غير موجود في المتغيرات!")

    if not APP_URL:
        raise ValueError("❌ APP_URL غير موجود في المتغيرات!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas))

    logger.info("🔥 Running BOT using WEBHOOK mode...")

    app.run_webhook(
        listen="0.0.0.0",
        port=8080,
        url_path=BOT_TOKEN,
        webhook_url=f"{APP_URL}/{BOT_TOKEN}"
    )


if __name__ == "__main__":
    main()
