import os
import logging
import requests
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # ضع رابط Koyeb هنا

app = Flask(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ===========================
#   SIMPLE PREMIUM ANALYSIS
# ===========================

def get_simple_analysis(symbol):
    try:
        data = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol.upper()}").json()

        if "lastPrice" not in data:
            return None

        last_price = float(data["lastPrice"])
        high = float(data["highPrice"])
        low = float(data["lowPrice"])

        return (
            f"📊 تحليل مبسط لزوج **{symbol.upper()}**\n\n"
            f"• آخر سعر: `{last_price}`\n"
            f"• أعلى سعر 24 ساعة: `{high}`\n"
            f"• أقل سعر 24 ساعة: `{low}`\n\n"
            f"📌 الاتجاه: {'صاعد 🚀' if last_price > (high + low) / 2 else 'هابط 🔻'}\n"
            f"⚠️ *تحليل مبسط – ليس نصيحة استثمارية*"
        )
    except:
        return None


# ===========================
#        TELEGRAM BOT
# ===========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 البوت شغال بنجاح عبر Webhook!\nأرسل: /analysis BTCUSDT")

async def analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        return await update.message.reply_text("❗ مثال: /analysis BTCUSDT")

    symbol = context.args[0].upper()
    result = get_simple_analysis(symbol)

    if result:
        await update.message.reply_text(result, parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ حدث خطأ أثناء تحليل الزوج.")


# ===========================
#       WEBHOOK HANDLER
# ===========================

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True))
    application.update_queue.put_nowait(update)
    return "OK", 200


# ===========================
#       MAIN APPLICATION
# ===========================

application = Application.builder().token(TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("analysis", analysis))


if __name__ == "__main__":
    # حذف أي Webhook قديم
    requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook")

    # تفعيل Webhook الجديد
    requests.get(
        f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={WEBHOOK_URL}/{TOKEN}"
    )

    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
