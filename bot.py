import os
import logging
import aiohttp
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
KOYEB_APP_NAME = os.getenv("KOYEB_APP_NAME")

if not BOT_TOKEN:
    raise Exception("❌ BOT_TOKEN is missing!")

if not KOYEB_APP_NAME:
    raise Exception("❌ KOYEB_APP_NAME is missing!")


# ---------------------------
# Fetch Ideas from TradingView
# ---------------------------
async def fetch_ideas(symbol: str):
    url = f"https://www.tradingview.com/symbols/{symbol}/ideas/"

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as response:
            html = await response.text()

    ideas = []

    parts = html.split('tv-feed__item tv-feed-layout__card-item')
    for block in parts[1:]:
        try:
            link_part = block.split('href="')[1].split('"')[0]
            full_link = "https://www.tradingview.com" + link_part

            title = block.split('tv-widget-idea__title">')[1].split("</")[0]

            img = block.split('data-src="')[1].split('"')[0]

            ideas.append({
                "title": title,
                "image": img,
                "url": full_link
            })

            if len(ideas) >= 10:
                break
        except:
            continue

    return ideas


# ---------------------------
# /start
# ---------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 أهلاً بك!\n\n"
        "هذا البوت يجلب لك أحدث أفكار وتحليلات TradingView لأي زوج كريبتو أو ذهب.\n\n"
        "✏️ الطريقة الأولى (مفضلة):\n"
        "/ideas BTCUSDT\n"
        "/ideas ETHUSDT\n"
        "/ideas GOLD\n\n"
        "✏️ الطريقة الثانية:\n"
        "اكتب رمز الزوج مباشرة مثل:\n"
        "/BTCUSDT\n"
        "/ETHUSDT\n"
        "/GOLD\n\n"
        "سيتم جلب حتى 20 فكرة (إذا كانت موجودة)."
    )
    await update.message.reply_text(text)


# ---------------------------
# /ideas BTCUSDT
# ---------------------------
async def ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("❌ استخدم: /ideas BTCUSDT")
        return

    symbol = context.args[0].upper()
    await send_ideas(symbol, update)


# ---------------------------
# Direct: /BTCUSDT
# ---------------------------
async def direct_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = update.message.text.replace("/", "").upper()
    await send_ideas(symbol, update)


# ---------------------------
# Send Ideas
# ---------------------------
async def send_ideas(symbol: str, update: Update):
    loading = await update.message.reply_text(f"⏳ جاري جلب أحدث الأفكار لـ {symbol} ...")

    ideas = await fetch_ideas(symbol)

    if not ideas:
        await loading.edit_text(f"⚠️ لا توجد أفكار متاحة حالياً لـ {symbol}.")
        return

    await loading.delete()

    for idea in ideas:
        text = f"📌 *{idea['title']}*\n🔗 {idea['url']}"
        await update.message.reply_photo(idea["image"], caption=text, parse_mode="Markdown")


# ---------------------------
# WEBHOOK MODE FOR KOYEB
# ---------------------------
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas))
    app.add_handler(MessageHandler(filters.Regex(r"^/[A-Za-z0-9]+$"), direct_symbol))

    webhook_url = f"https://{KOYEB_APP_NAME}.koyeb.app/webhook/{BOT_TOKEN}"

    await app.run_webhook(
        listen="0.0.0.0",
        port=8000,
        url_path=BOT_TOKEN,
        webhook_url=webhook_url
    )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
