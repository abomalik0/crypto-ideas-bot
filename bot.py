import os
import logging
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing!")

TV_BASE = "https://www.tradingview.com"


def fetch_ideas(symbol: str, max_ideas: int = 20):
    url = f"{TV_BASE}/symbols/{symbol}/ideas/"
    logger.info(f"Fetching {url}")

    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    except:
        return []

    if r.status_code != 200:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    cards = soup.find_all("article")

    ideas = []
    for c in cards:
        a = c.find("a", href=True)
        if not a:
            continue

        link = TV_BASE + a["href"]
        img = c.find("img")
        image = img["src"] if img else None
        title_tag = c.find("span") or c.find("h2") or c.find("h3")
        title = title_tag.get_text(strip=True) if title_tag else "TradingView Idea"

        ideas.append({"title": title, "image": image, "link": link})
        if len(ideas) >= max_ideas:
            break

    return ideas


WELCOME = (
    "أهلاً 👋\n"
    "استخدم:\n"
    "/ideas BTCUSDT\n"
    "أو مباشرة:\n"
    "/BTCUSDT"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)


def extract_symbol(text: str):
    if text.startswith("/ideas"):
        parts = text.split()
        return parts[1].upper() if len(parts) > 1 else None

    if text.startswith("/"):
        return text[1:].upper()

    return None


async def ideas_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    symbol = extract_symbol(txt)

    if not symbol:
        await update.message.reply_text("اكتب: /ideas BTCUSDT")
        return

    loading = await update.message.reply_text(f"⏳ يجري جلب أفكار {symbol}")

    loop = context.application.loop
    ideas = await loop.run_in_executor(None, fetch_ideas, symbol)

    if not ideas:
        await loading.edit_text(f"لا يوجد أفكار حالياً لـ {symbol}")
        return

    await loading.delete()

    for idea in ideas:
        caption = f"{idea['title']}\n\n🔗 {idea['link']}"

        # لو في صورة
        if idea["image"]:
            try:
                await update.message.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=idea["image"],
                    caption=caption,
                )
                continue
            except:
                pass

        # لو فشل إرسال الصورة → أرسل نص فقط
        await update.message.bot.send_message(
            chat_id=update.effective_chat.id,
            text=caption
        )


async def shortcut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    update.message.text = f"/ideas {update.message.text[1:]}"
    await ideas_cmd(update, context)


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas_cmd))
    app.add_handler(
        MessageHandler(filters.Regex(r"^/[A-Za-z0-9]+$"), shortcut)
    )

    port = int(os.getenv("PORT", "8080"))

    logger.info(f"Webhook running on port {port}")

    # أهم نقطة: **بدون await – بدون إغلاق Event Loop**
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=None,
    )


if __name__ == "__main__":
    main()
