import os
import logging
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup

from telegram import Update, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ----------------- إعداد اللوجز -----------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ----------------- إعداد التوكن -----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN is missing from environment variables!")

# TradingView base URL
TV_BASE = "https://www.tradingview.com"


# ----------------- دالة جلب أفكار TradingView -----------------
def fetch_tradingview_ideas(symbol: str, max_ideas: int = 20) -> List[Dict[str, Optional[str]]]:
    """
    Fetch up to `max_ideas` ideas for the given symbol from TradingView.
    Returns a list of dicts: {title, author, image_url, link}.
    If no ideas found, returns empty list.
    """
    symbol = symbol.upper()
    ideas_url = f"{TV_BASE}/symbols/{symbol}/ideas/"

    logger.info("Fetching ideas page for %s: %s", symbol, ideas_url)

    try:
        resp = requests.get(
            ideas_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
    except Exception as e:
        logger.warning("Error while requesting TradingView: %s", e)
        return []

    if resp.status_code != 200:
        logger.warning("TradingView returned status %s for %s", resp.status_code, ideas_url)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # TradingView تغير شكل الصفحة من وقت للتانى,
    # فنختار كل الـ <article> ونحاول نستخرج منها لينك + صورة + عنوان + كاتب.
    articles = soup.find_all("article")
    ideas: List[Dict[str, Optional[str]]] = []

    for art in articles:
        link_tag = art.find("a", href=True)
        if not link_tag:
            continue

        href = link_tag["href"]
        if not href.startswith("/"):
            continue

        full_link = TV_BASE + href

        # العنوان
        title_tag = art.find("span") or art.find("h2") or art.find("h3")
        title = title_tag.get_text(strip=True) if title_tag else "TradingView Idea"

        # الكاتب (لو ظاهر)
        author_tag = art.find("a", class_="tv-user-link")
        author = author_tag.get_text(strip=True) if author_tag else None

        # الصورة
        img_tag = art.find("img")
        image_url = img_tag["src"] if img_tag and img_tag.get("src") else None

        ideas.append(
            {
                "title": title,
                "author": author,
                "image_url": image_url,
                "link": full_link,
            }
        )

        if len(ideas) >= max_ideas:
            break

    if not ideas:
        logger.warning("No chart links found on ideas page for %s", symbol)

    return ideas


# ----------------- Handlers فى التليجرام -----------------
WELCOME_TEXT = (
    "أهلاً بك! 👋\n"
    "هذا البوت يجلب لك أحدث أفكار وتحليلات 📈 من TradingView (Chart Ideas)\n"
    "لأي زوج كريبتو أو عملات أو ذهب…\n\n"
    "🧾 الطريقة الأولى (مفضّلة):\n"
    "/ideas BTCUSDT\n"
    "/ideas BTCUSD\n"
    "/ideas ETHUSDT\n"
    "/ideas GOLD\n\n"
    "📝 الطريقة الثانية:\n"
    "اكتب اسم الزوج كأمر مباشرة، مثل:\n"
    "/BTCUSDT\n"
    "/BTCUSD\n"
    "/ETHUSDT\n"
    "/GOLD\n\n"
    "سيتم جلب حتى 20 فكرة (إذا كانت موجودة) وإرسال كل فكرة في رسالة منفصلة مع الصورة والعنوان.\n\n"
    "English:\n"
    "Send /ideas SYMBOL like /ideas BTCUSDT and I'll fetch the latest TradingView "
    "chart ideas with image, title, author and link.\n"
    "You can also send /BTCUSDT directly."
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME_TEXT)


def _extract_symbol_from_text(text: str) -> Optional[str]:
    """
    Takes e.g. '/ideas BTCUSDT' or '/BTCUSDT' and returns 'BTCUSDT'
    or None if can't parse.
    """
    if not text:
        return None

    text = text.strip()

    # حالة /ideas BTCUSDT
    if text.lower().startswith("/ideas"):
        parts = text.split()
        if len(parts) < 2:
            return None
        return parts[1].replace("/", "").upper()

    # حالة /BTCUSDT
    if text.startswith("/"):
        return text[1:].upper()

    return None


async def handle_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler لأمر /ideas SYMBOL
    """
    message_text = update.message.text or ""
    symbol = _extract_symbol_from_text(message_text)

    if not symbol:
        await update.message.reply_text("❗️ اكتب الأمر بهذا الشكل:\n/ideas BTCUSDT")
        return

    waiting_msg = await update.message.reply_text(
        f"⏳ جارى جلب أحدث الأفكار لـ {symbol} ..."
    )

    # جلب الأفكار فى ثريد منفصل عشان منوقفش event loop
    loop = context.application.loop
    ideas = await loop.run_in_executor(None, fetch_tradingview_ideas, symbol)

    if not ideas:
        await waiting_msg.edit_text(
            f"⚠️ لا توجد أفكار متاحة حالياً على TradingView للزوج {symbol}.\n"
            f"No ideas found on TradingView right now for {symbol}."
        )
        return

    await waiting_msg.delete()

    # إرسال كل فكرة فى رسالة
    for idea in ideas:
        title = idea["title"] or "TradingView Idea"
        author = idea.get("author")
        link = idea.get("link") or TV_BASE
        image_url = idea.get("image_url")

        caption = f"{title}\n\n🔗 {link}"
        if author:
            caption = f"{title}\n\n✍️ {author}\n🔗 {link}"

        # لو فى صورة نحاول نبعتها؛ لو فشل نبعت النص بس
        if image_url:
            try:
                await update.message.bot.send_photo(
                    chat_id=update.effective_chat.id,
                    photo=image_url,
                    caption=caption,
                )
                continue
            except Exception as e:
                logger.warning("Error sending photo: %s", e)

        await update.message.bot.send_message(
            chat_id=update.effective_chat.id,
            text=caption,
        )


async def handle_symbol_shortcut(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler لرسائل زى /BTCUSDT أو /GOLD
    يستخدم نفس دالة handle_ideas لكن نحول النص لشكل /ideas SYMBOL
    """
    text = update.message.text or ""
    symbol = _extract_symbol_from_text(text)
    if not symbol:
        return

    # نعيد استخدام نفس المنطق عن طريق استدعاء handle_ideas
    # بس نعدل text فى الـ update شوية
    update.message.text = f"/ideas {symbol}"
    await handle_ideas(update, context)


# ----------------- main (بدون asyncio.run) -----------------
def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("ideas", handle_ideas))

    # أى رسالة من نوع /SYMBOL (من غير مساحة) تعتبر Shortcut
    application.add_handler(
        MessageHandler(
            filters.Regex(r"^/[A-Za-z0-9]{3,20}$") & ~filters.COMMAND,
            handle_symbol_shortcut,
        )
    )

    # إعداد الويب هوك:
    # إحنا افترضنا إنك عملت setWebhook بـ:
    # https://YOUR_KOYEB_URL/<BOT_TOKEN>
    # لذلك هنخلى url_path = BOT_TOKEN ونسيب Telegram يستخدم نفس الـ URL
    port = int(os.getenv("PORT", "8080"))

    logger.info("Starting bot via webhook on port %s ...", port)

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,   # لازم يطابق آخر جزء فى الـ URL بتاع setWebhook
        # webhook_url مش محتاجينه هنا لأنك حددته بنفسك عن طريق API
        webhook_url=None,
    )


if __name__ == "__main__":
    main()
