import os
import requests
from datetime import datetime
from telegram import Update, InputMediaPhoto
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise Exception("❌ ERROR: BOT_TOKEN is missing in environment variables!")

API_URL = "https://www.tradingview.com/ideas-page/?symbol={symbol}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

# ============================
# 🔥 Fetch ideas from TradingView Hidden API
# ============================
def fetch_tv_ideas(symbol: str):
    url = API_URL.format(symbol=symbol.upper())

    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    ideas = []
    for i in data.get("ideas", []):
        try:
            idea = {
                "title": i.get("headline", "بدون عنوان"),
                "author": i.get("author", {}).get("username", "غير معروف"),
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
                    idea["published"] = "غير معروف"

            ideas.append(idea)
        except:
            continue

    return ideas


# ============================
# /start
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 أهلاً! أرسل لي رمز العملة مثل:\n"
        "`/ideas BTCUSDT`\n\n"
        "وسأجلب لك أحدث الأفكار من TradingView 🔥"
    )
    await update.message.reply_markdown(text)


# ============================
# /ideas BTCUSDT
# ============================
async def ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("⚠️ استخدم: `/ideas BTCUSDT`", parse_mode="Markdown")
        return

    symbol = context.args[0].upper()

    await update.message.reply_text(f"⏳ جاري جلب أحدث الأفكار لـ *{symbol}* ...", parse_mode="Markdown")

    ideas = fetch_tv_ideas(symbol)

    if not ideas:
        await update.message.reply_text(
            f"⚠️ لا توجد أفكار متاحة حاليًا على TradingView لزوج *{symbol}*.",
            parse_mode="Markdown"
        )
        return

    # Send up to 3 ideas
    for idea in ideas[:3]:
        caption = (
            f"🔥 *{idea['title']}*\n"
            f"✍️ الكاتب: `{idea['author']}`\n"
            f"🕒 التاريخ: `{idea['published']}`\n"
            f"🔗 الرابط:\n{idea['url']}"
        )

        if idea["image"]:
            await update.message.reply_photo(idea["image"], caption=caption, parse_mode="Markdown")
        else:
            await update.message.reply_markdown(caption)


# ============================
# 🚀 Run Bot (Webhook Mode)
# ============================
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas))

    print("✅ Bot is running via Webhook on Koyeb...")

    await app.run_webhook(
        listen="0.0.0.0",
        port=8080,
        url_path=BOT_TOKEN,
        webhook_url=f"https://{os.getenv('KOYEB_APP_NAME')}.koyeb.app/{BOT_TOKEN}",
    )

import asyncio
asyncio.run(main())
