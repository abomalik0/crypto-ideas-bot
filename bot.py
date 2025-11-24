import logging
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# -----------------------------------
# Logging
# -----------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# -----------------------------------
# TradingView Scraper
# -----------------------------------
BASE_URL = "https://scanner.tradingview.com/crypto/scan"

def get_tv_ideas(symbol: str):
    if symbol.endswith("USDT"):
        search_pair = symbol.replace("USDT", "USD")
    else:
        search_pair = symbol

    payload = {
        "symbols": {"tickers": [f"BINANCE:{search_pair}"]},
        "columns": ["name", "description", "relatedIdeas"]
    }

    try:
        response = requests.post(BASE_URL, json=payload, timeout=10)
        data = response.json()
        ideas_raw = data.get("data", [{}])[0].get("d", [])

        ideas = []
        for idea in ideas_raw:
            ideas.append({
                "title": idea.get("title", "No title"),
                "link": "https://www.tradingview.com" + idea.get("link", "")
            })

        return ideas[:10]

    except Exception as e:
        print("TradingView API Error:", e)
        return []

# -----------------------------------
# /start command
# -----------------------------------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحباً! 👋\n"
        "استخدم:\n/ideas BTCUSDT\n"
        "أو اكتب مباشرة /BTCUSDT وسيتم جلب الأفكار."
    )

# -----------------------------------
# /ideas command
# -----------------------------------
async def ideas_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if len(context.args) == 0:
        await update.message.reply_text("❗ لازم تكتب زوج مثل: /ideas BTCUSDT")
        return

    symbol = context.args[0].upper().strip()

    await update.message.reply_text(f"⏳ جاري جلب أفكار {symbol} من TradingView...")

    ideas = get_tv_ideas(symbol)

    if not ideas:
        await update.message.reply_text("⚠️ لا توجد أفكار متاحة حالياً.")
        return

    for idea in ideas:
        await update.message.reply_text(f"📌 {idea['title']}\n🔗 {idea['link']}")

# -----------------------------------
# Shortcuts for /BTCUSDT etc.
# -----------------------------------
async def shortcut_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = update.message.text.replace("/", "").upper()
    fake_context = type("Fake", (), {})()
    fake_context.args = [symbol]
    return await ideas_cmd(update, fake_context)

# -----------------------------------
# MAIN
# -----------------------------------
def main():
    BOT_TOKEN = "ضع_التوكن_هنا"

    application = Application.builder().token(BOT_TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("ideas", ideas_cmd))

    # Shortcut commands for tickers
    shortcuts = ["BTCUSDT", "ETHUSDT", "BTCUSD", "ETHUSD", "GOLD"]
    for s in shortcuts:
        application.add_handler(CommandHandler(s.lower(), shortcut_cmd))

    print("Bot started in polling mode...")
    application.run_polling()

if __name__ == "__main__":
    main()
