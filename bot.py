import os
import logging
import time
from typing import List, Dict

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

# -------------------- الإعدادات العامة --------------------

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("⚠️ متنساش تضيف BOT_TOKEN كـ Environment Variable في Koyeb")

TV_BASE = "https://www.tradingview.com"
MAX_IDEAS = 15          # أقصى عدد أفكار ترجع لكل طلب
RATE_LIMIT_SECONDS = 10  # ثواني بين كل طلب وطلب لنفس الشخص

# user_id -> last_timestamp
last_request_time: Dict[int, float] = {}

# -------------------- اللوجينج --------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# -------------------- دوال مساعدة --------------------


def is_rate_limited(user_id: int) -> bool:
    """منع السبام: كل يوزر له طلب كل X ثواني."""
    now = time.time()
    last = last_request_time.get(user_id, 0)
    if now - last < RATE_LIMIT_SECONDS:
        return True
    last_request_time[user_id] = now
    return False


def fetch_ideas(symbol: str, max_ideas: int = MAX_IDEAS) -> List[Dict[str, str]]:
    """
    سكراب بسيط لأفكار TradingView لزوج معين.
    يرجع قائمة من dict فيها: title, image, link
    """
    url = f"{TV_BASE}/symbols/{symbol}/ideas/"
    logger.info(f"Fetching ideas from: {url}")

    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CryptoIdeasBot/1.0)"},
            timeout=15,
        )
    except Exception as e:
        logger.exception("Network error while fetching ideas: %s", e)
        return []

    if r.status_code != 200:
        logger.warning("TradingView returned status %s", r.status_code)
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    cards = soup.find_all("article")

    ideas: List[Dict[str, str]] = []
    for c in cards:
        a = c.find("a", href=True)
        if not a:
            continue

        link = TV_BASE + a["href"]

        img = c.find("img")
        image = img["src"] if img and img.has_attr("src") else None

        title_tag = c.find("span") or c.find("h2") or c.find("h3")
        title = title_tag.get_text(strip=True) if title_tag else "TradingView Idea"

        ideas.append({"title": title, "image": image, "link": link})

        if len(ideas) >= max_ideas:
            break

    return ideas


def normalize_symbol(raw: str) -> str:
    """تظبيط البير: remove spaces + upper case."""
    return raw.replace(" ", "").upper()


WELCOME = (
    "أهلاً بيك 👋\n\n"
    "أنا بوت بيجيب لك أحدث الأفكار (Ideas) من TradingView لرموز الكريبتو وغيرها.\n\n"
    "طريقة الاستخدام:\n"
    "• اكتب الأمر:\n"
    "  `/ideas BTCUSDT`\n"
    "• أو اختصاراً اكتب:\n"
    "  `/BTCUSDT`\n\n"
    "كل أمر بيرجع لك آخر الأفكار المنشورة للرمز اللي كتبته ✅"
)


# -------------------- Handlers --------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME)


async def ideas_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """هاندلر /ideas BTCUSDT"""
    if not update.message:
        return

    user_id = update.effective_user.id

    if is_rate_limited(user_id):
        await update.message.reply_text("⏳ من فضلك استنى ثواني بين كل طلب و التاني.")
        return

    if not context.args:
        await update.message.reply_text("اكتب الأمر كده:\n/ideas BTCUSDT")
        return

    symbol = normalize_symbol(context.args[0])
    await handle_symbol(symbol, update, context)


async def shortcut_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    أي أمر بالشكل /BTCUSDT /ETHUSDT ... الخ
    ماعدا الأوامر المحجوزة (start, ideas).
    """
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id

    if is_rate_limited(user_id):
        await update.message.reply_text("⏳ من فضلك استنى ثواني بين كل طلب و التاني.")
        return

    raw = update.message.text[1:]  # شيل الـ /
    symbol = normalize_symbol(raw)

    # لو حد كتب /start أو /ideas بالغلط هنا
    if symbol.upper() in ("START", "IDEAS"):
        return

    await handle_symbol(symbol, update, context)


async def handle_symbol(symbol: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """الكود المشترك بين /ideas و /BTCUSDT."""
    chat_id = update.effective_chat.id

    loading_msg = await update.message.reply_text(f"⏳ بيتم جلب أفكار **{symbol}** من TradingView ...")

    # شغّل السكراب في thread منفصل عشان مبلوكش البوت
    loop = context.application.loop
    ideas = await loop.run_in_executor(None, fetch_ideas, symbol)

    if not ideas:
        await loading_msg.edit_text(f"⚠️ لا يوجد أفكار حالياً للرمز: {symbol}")
        return

    await loading_msg.delete()

    for idea in ideas:
        caption = f"{idea['title']}\n\n🔗 {idea['link']}"
        image = idea.get("image")

        if image:
            try:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=image,
                    caption=caption,
                )
                continue
            except Exception as e:
                logger.warning("Failed to send photo, fallback to text. Error: %s", e)

        await context.bot.send_message(chat_id=chat_id, text=caption)


# -------------------- Main --------------------


def main() -> None:
    """نقطة البداية – بنستخدم polling عشان نريح دماغنا من الـ Webhook."""
    application = Application.builder().token(BOT_TOKEN).build()

    # أوامر قياسية
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ideas", ideas_command))

    # أي أمر بالشكل /BTCUSDT /ETH ... إلخ
    application.add_handler(
        MessageHandler(
            filters.COMMAND & filters.Regex(r"^/[A-Za-z0-9]+$"),
            shortcut_command,
        )
    )

    logger.info("Bot is starting with polling...")
    # Run forever
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
