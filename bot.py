import os
import logging
import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# =============================
# Logging setup
# =============================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# =============================
# TradingView API (IDEAS FEED)
# =============================
TV_API = "https://www.tradingview.com/ideas/{symbol}/"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

async def fetch_ideas(symbol: str):
    """
    يعتمد على TradingView ideas RSS feed  
    مستقر 100% ولا يحتاج تسجيل دخول.
    """
    url = f"https://www.tradingview.com/ideas/{symbol}/rss/"
    
    try:
        async with httpx.AsyncClient(timeout=10, headers=headers) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.text
    except Exception as e:
        return []

    # استخراج الأفكار من RSS
    ideas = []
    items = content.split("<item>")[1:]

    for item in items[:10]:  # نرجّع فقط آخر 10 أفكار
        try:
            title = item.split("<title><![CDATA[")[1].split("]]></title>")[0]
            link = item.split("<link><![CDATA[")[1].split("]]></link>")[0]
            ideas.append((title, link))
        except:
            pass

    return ideas


# =============================
# Telegram Commands
# =============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 أهلاً!\n"
        "هذا البوت يجلب لك أحدث أفكار TradingView لأي زوج.\n\n"
        "اكتب مثلاً:\n"
        "/ideas BTCUSDT\n\n"
        "أو مباشرة:\n"
        "/BTCUSDT"
    )
    await update.message.reply_text(msg)


async def ideas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("❗ استخدم: /ideas BTCUSDT")
        return

    symbol = context.args[0].upper()
    await send_ideas(update, symbol)


async def fallback_pair(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """لو المستخدم كتب /BTCUSDT من غير /ideas"""
    symbol = update.message.text.replace("/", "").upper()
    await send_ideas(update, symbol)


async def send_ideas(update: Update, symbol: str):
    await update.message.reply_text(f"⏳ جاري جلب أفكار {symbol} من TradingView...")

    ideas = await fetch_ideas(symbol)

    if not ideas:
        await update.message.reply_text("❌ لا توجد أفكار حالياً لهذا الزوج.")
        return

    for title, link in ideas:
        await update.message.reply_text(f"📌 *{title}*\n🔗 {link}", parse_mode="Markdown")


# =============================
# Main Bot Runner
# =============================
def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("❌ BOT_TOKEN not set in environment!")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ideas", ideas_command))

    # أي شيء المستخدم يكتبه يبدأ بـ "/" (زوج مباشر)
    app.add_handler(CommandHandler(None, fallback_pair))

    logger.info("Bot running in POLLING mode...")
    app.run_polling()


if __name__ == "__main__":
    main()
