import os
import time
import logging
from typing import Optional, Dict, List, Tuple

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

# ---------- إعداد اللوج ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------- التوكن من المتغيرات ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Environment variable BOT_TOKEN is missing!")

TV_BASE = "https://www.tradingview.com"

MAX_IDEAS = 10          # عدد الأفكار لكل رمز
CACHE_TTL = 120         # مدة الكاش بالثواني
RATE_LIMIT_SECONDS = 5   # أقل وقت بين طلبين لنفس اليوزر

# كاش للأفكار: symbol -> (timestamp, ideas-list)
ideas_cache: Dict[str, Tuple[float, List[Dict]]] = {}

# آخر طلب لكل يوزر: user_id -> timestamp
user_last_request: Dict[int, float] = {}


# ---------- دالة سحب الأفكار من TradingView ----------
def fetch_ideas(symbol: str, max_ideas: int = MAX_IDEAS) -> List[Dict]:
    url = f"{TV_BASE}/symbols/{symbol}/ideas/"
    logger.info("Fetching ideas for %s -> %s", symbol, url)

    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    except Exception as e:
        logger.exception("Request error: %s", e)
        return []

    if r.status_code != 200:
        logger.warning("TradingView returned %s for %s", r.status_code, url)
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    cards = soup.find_all("article")

    ideas: List[Dict] = []
    for c in cards:
        a = c.find("a", href=True)
        if not a:
            continue

        link = TV_BASE + a["href"]
        img = c.find("img")
        image = img["src"] if img and img.get("src") else None
        title_tag = c.find("span") or c.find("h2") or c.find("h3")
        title = title_tag.get_text(strip=True) if title_tag else "TradingView idea"

        ideas.append({"title": title, "image": image, "link": link})
        if len(ideas) >= max_ideas:
            break

    return ideas


WELCOME = (
    "أهلاً 👋\n\n"
    "هذا البوت يجيب لك آخر أفكار TradingView لأي زوج كريبتو أو ذهب.\n\n"
    "استخدم مثلاً:\n"
    "/ideas BTCUSDT\n"
    "أو مباشرةً:\n"
    "/BTCUSDT\n\n"
    "سيتم إرسال حتى 10 أفكار في رسائل منفصلة مع العنوان والرابط."
)


# ---------- هاندلر /start ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text(WELCOME)


# ---------- استخراج الرمز من النص ----------
def extract_symbol(text: str) -> Optional[str]:
    text = text.strip()

    if text.startswith("/ideas"):
        parts = text.split()
        if len(parts) > 1:
            return parts[1].upper()
        return None

    if text.startswith("/") and len(text) > 1:
        return text[1:].upper()

    return None


# ---------- Rate limit ----------
def check_rate_limit(user_id: int) -> int:
    """
    يرجع 0 لو مسموح
    أو عدد الثواني اللي لازم ينتظرها لو مستعجل
    """
    now = time.time()
    last = user_last_request.get(user_id, 0)
    diff = now - last

    if diff < RATE_LIMIT_SECONDS:
        return int(RATE_LIMIT_SECONDS - diff)

    user_last_request[user_id] = now
    return 0


# ---------- الكاش ----------
def get_cached_ideas(symbol: str) -> Optional[List[Dict]]:
    now = time.time()
    entry = ideas_cache.get(symbol)

    if not entry:
        return None

    ts, ideas = entry
    if now - ts > CACHE_TTL:
        return None

    return ideas


def set_cached_ideas(symbol: str, ideas: List[Dict]) -> None:
    ideas_cache[symbol] = (time.time(), ideas)


# ---------- هاندلر /ideas ----------
async def ideas_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user_id = update.effective_user.id if update.effective_user else 0

    # Rate limit
    wait = check_rate_limit(user_id)
    if wait > 0:
        await update.message.reply_text(
            f"⏳ من فضلك انتظر {wait} ثواني قبل طلب جديد 🙂"
        )
        return

    txt = update.message.text
    symbol = extract_symbol(txt)

    if not symbol:
        await update.message.reply_text("استخدم الأمر بهذا الشكل:\n/ideas BTCUSDT")
        return

    # جرب الكاش أولاً
    ideas = get_cached_ideas(symbol)

    if ideas is None:
        loading = await update.message.reply_text(
            f"⏳ جاري جلب أفكار {symbol} من TradingView..."
        )

        # تشغيل scrape في thread منفصل (عشان ما يوقفش البوت)
        ideas = await context.application.run_in_executor(
            None, fetch_ideas, symbol
        )

        if not ideas:
            await loading.edit_text(f"لم أجد أفكار حالياً لـ {symbol} 😔")
            return

        set_cached_ideas(symbol, ideas)
        await loading.delete()

    # إرسال الأفكار
    for idea in ideas:
        caption = f"{idea['title']}\n\n🔗 {idea['link']}"

        if idea["image"]:
            try:
                await update.message.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=idea["image"],
                    caption=caption,
                )
                continue
            except Exception as e:
                logger.warning("Failed to send photo: %s", e)

        # لو مافيش صورة أو فشل إرسالها → نص فقط
        await update.message.bot.send_message(
            chat_id=update.effective_chat.id,
            text=caption,
        )


# ---------- شورت كات /BTCUSDT ----------
async def shortcut(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    # نحول /BTCUSDT -> "/ideas BTCUSDT"
    update.message.text = f"/ideas {update.message.text[1:]}"
    await ideas_cmd(update, context)


# ---------- main ----------
def main():
    logger.info("Starting bot in POLLING mode...")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas_cmd))
    app.add_handler(MessageHandler(filters.Regex(r"^/[A-Za-z0-9]+$"), shortcut))

    # أهم حاجة: تشغيل الـ polling فقط
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
