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
# 🔑 BOT TOKEN
# ========================
TOKEN = os.getenv("BOT_TOKEN")
APP_NAME = os.getenv("KOYEB_APP_NAME")

if not TOKEN:
    raise Exception("❌ ERROR: BOT_TOKEN is missing!")

if not APP_NAME:
    raise Exception("❌ ERROR: KOYEB_APP_NAME is missing!")


# ========================
# 🔥 TradingView Hidden API
# ========================
API_URL = "https://www.tradingview.com/ideas-page/?symbol={symbol}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123 Safari/537.36"
    )
}

def get_tv_ideas(symbol: str):
    url = API_URL.format(symbol=symbol.upper())

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
    except:
        return []

    ideas = []
    for i in data.get("ideas", []):
        idea = {
            "title": i.get("headline", "No title"),
            "author": i.get("author", {}).get("username", "Unknown"),
            "image": i.get("thumb_url", None),
            "published": i.get("published_datetime", None),
            "url": f"https://www.tradingview.com{i.get('public_id','')}",
        }

        # Convert timestamp
        if idea["published"]:
            try:
                idea["published"] = datetime.fromtimestamp(
                    idea["published"]
                ).strftime("%Y-%m-%d %H:%M")
            except:
                idea["published"] = "Unknown"

        ideas.append(idea)

    return ideas


# ========================
# /start
# ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 أهلاً بك!\n\n"
        "أرسل:\n"
        "`/ideas BTCUSDT`\n"
        "وسأجلب لك أحدث أفكار TradingView مع الصورة والعنوان والكاتب.\n\n"
        "English:\n"
        "Send `/ideas BTCUSDT` to get the latest TradingView ideas."
    )
    await update.message.reply_markdown(msg)


# ========================
# /ideas BTCUSDT
# ========================
async def ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "⚠️ استخدم:\n/ideas BTCUSDT\n\nUse: /ideas SYMBOL"
        )
        return

    symbol = context.args[0].upper()

    await update.message.reply_text(f"⏳ Fetching ideas for *{symbol}* ...", parse_mode="Markdown")

    ideas = get_tv_ideas(symbol)

    if not ideas:
        msg = (
            f"⚠️ لا توجد أفكار متاحة حالياً على TradingView للزوج {symbol}.\n"
            f"No ideas found on TradingView right now for {symbol}."
        )
        await update.message.reply_text(msg)
        return

    # ارسال أول 3 أفكار
    for idea in ideas[:3]:

        caption = (
            f"🔥 *{idea['title']}*\n"
            f"✍️ الكاتب: `{idea['author']}`\n"
            f"🕒 التاريخ: `{idea['published']}`\n"
            f"🔗 الرابط:\n{idea['url']}"
        )

        if idea["image"]:
            await update.message.reply_photo(
                idea["image"],
                caption=caption,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_markdown(caption)


# ========================
# 🚀 Webhook Mode (Koyeb)
# ========================
async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas))

    print("🚀 Bot is running on Koyeb Webhook...")

    await app.run_webhook(
        listen="0.0.0.0",
        port=8080,
        url_path=TOKEN,
        webhook_url=f"https://{APP_NAME}.koyeb.app/{TOKEN}",
    )

import asyncio
asyncio.run(main())
