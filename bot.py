import logging
import time
from telegram.ext import Updater, CommandHandler
from telegram import ParseMode
import os
from datetime import datetime
import requests

# --------------------------------------
# Telegram TOKEN from environment variable
# --------------------------------------
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise Exception("❌ ERROR: BOT_TOKEN is missing in environment variables!")

# --------------------------------------
# Logging
# --------------------------------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --------------------------------------
# TradingView Ideas Fetcher
# --------------------------------------
def fetch_symbol_ideas(symbol: str, limit: int = 20):
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
                "id": i.get("public_id", "")
            }

            # Convert timestamp
            try:
                idea["published_dt"] = datetime.fromtimestamp(
                    idea["published_raw"]
                ).strftime("%Y-%m-%d %H:%M")
            except:
                idea["published_dt"] = "Unknown"

            ideas.append(idea)
        except Exception:
            continue

    return ideas

# --------------------------------------
# Telegram Commands
# --------------------------------------
def start(update, context):
    update.message.reply_text(
        "👋 أهلاً! ابعت لي رمز العملة مثل:\n\n"
        "`/ideas BTCUSDT`\n\n"
        "وهجبلك أحدث أفكار TradingView 🔥",
        parse_mode=ParseMode.MARKDOWN
    )

def ideas_cmd(update, context):
    if len(context.args) == 0:
        return update.message.reply_text("❗ استخدم:\n/ideas BTCUSDT")

    symbol = context.args[0]
    update.message.reply_text(f"⏳ جاري جلب أحدث الأفكار لـ *{symbol}* ...", parse_mode=ParseMode.MARKDOWN)

    ideas = fetch_symbol_ideas(symbol)

    if not ideas:
        return update.message.reply_text("⚠️ لا يوجد أفكار حالياً!")

    for idea in ideas[:5]:
        text = (
            f"📌 *{idea['title']}*\n"
            f"✍️ الكاتب: `{idea['author']}`\n"
            f"🕒 الوقت: `{idea['published_dt']}`\n"
            f"🔗 https://www.tradingview.com/chart/{symbol}/{idea['id']}/"
        )
        update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# --------------------------------------
# Main Loop (Polling)
# --------------------------------------
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # Commands
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("ideas", ideas_cmd))

    # Start bot
    updater.start_polling()
    logger.info("🚀 Bot is running with long polling")
    updater.idle()

if __name__ == "__main__":
    main()
