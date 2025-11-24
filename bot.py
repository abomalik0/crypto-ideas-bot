import os
import logging
import httpx
import xml.etree.ElementTree as ET

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

# =========================
# إعداد اللوجز
# =========================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# =========================
# إعداد TradingView
# =========================
TV_RSS = "https://www.tradingview.com/ideas/{symbol}/rss/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}


async def fetch_ideas(symbol: str, limit: int = 10):
    """
    يجيب آخر الأفكار من TradingView لزوج معين من RSS.
    يرجّع List of (title, link)
    """
    url = TV_RSS.format(symbol=symbol.upper())
    logger.info("Fetching ideas for %s from %s", symbol, url)

    try:
        async with httpx.AsyncClient(timeout=15.0, headers=HEADERS) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.text
    except Exception as e:
        logger.error("HTTP error while fetching RSS for %s: %s", symbol, e)
        return []

    try:
        # Parse XML RSS
        root = ET.fromstring(content)
        items = root.findall(".//item")
        ideas = []

        for item in items[:limit]:
            title = item.findtext("title", default="(بدون عنوان)").strip()
            link = item.findtext("link", default="").strip()

            if not link:
                continue

            ideas.append((title, link))

        logger.info("Found %d ideas for %s", len(ideas), symbol)
        return ideas
    except Exception as e:
        logger.error("Parse error while reading RSS for %s: %s", symbol, e)
        return []


# =========================
# أوامر التليجرام
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "أهلًا 👋\n\n"
        "هذا البوت يجيب لك آخر أفكار TradingView لأي زوج كريبتو أو ذهب أو غيره.\n\n"
        "استخدم مثلًا:\n"
        "/ideas BTCUSDT\n"
        "أو:\n"
        "/ideas ETHUSD\n\n"
        "ويمكنك أيضًا إرسال الزوج مباشرة كأمر:\n"
        "/BTCUSDT\n"
        "/GOLD\n\n"
        "سيتم إرسال حتى 10 أفكار في رسائل منفصلة مع العنوان والرابط."
    )
    await update.message.reply_text(msg)


async def ideas_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    أمر: /ideas SYMBOL
    """
    if not context.args:
        await update.message.reply_text("❌ استخدم الأمر بهذا الشكل: /ideas BTCUSDT")
        return

    symbol = context.args[0].upper()
    await update.message.reply_text(
        f"⏳ جاري جلب أفكار {symbol} من TradingView..."
    )

    await send_ideas(update, symbol)


async def symbol_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    لما تكتب /BTCUSDT أو /GOLD مباشرة.
    """
    text = (update.message.text or "").strip()
    # نشيل أول "/" لو موجودة
    symbol = text.lstrip("/").split()[0].upper()

    if not symbol:
        await update.message.reply_text("❌ لم يتم التعرف على الزوج.")
        return

    await update.message.reply_text(
        f"⏳ جاري جلب أفكار {symbol} من TradingView..."
    )

    await send_ideas(update, symbol)


async def send_ideas(update: Update, symbol: str) -> None:
    ideas = await fetch_ideas(symbol)

    if not ideas:
        await update.message.reply_text(
            f"❌ لا يوجد أفكار لهذا الزوج أو حدث خطأ.\nالزوج: {symbol}"
        )
        return

    # نرسل كل فكرة في رسالة منفصلة
    for title, link in ideas:
        text = f"📌 *{title}*\n🔗 {link}"
        await update.message.reply_text(text, parse_mode="Markdown")


# =========================
# نقطة تشغيل البوت
# =========================
def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("❌ متغير البيئة BOT_TOKEN غير موجود!")

    app = Application.builder().token(token).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas_command))

    # أمر عام لأي /SYMBOL
    app.add_handler(CommandHandler(["BTC", "ETH", "BTCUSDT", "ETHUSDT", "GOLD"], symbol_command))
    # ولو حابب تخلي أي حاجة تبدأ بـ / تتفسر كـ symbol:
    # يفضّل تسيبه ثابت زي فوق عشان ما يحصلش تضارب مع أوامر تانية

    logger.info("Bot is running in POLLING mode...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
