import os
import requests
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

app = Flask(__name__)

# ===============================
#  Telegram Bot Handlers
# ===============================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 أهلاً! البوت شغال!")

async def ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📌 جارى جلب الأفكار...")

async def analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 جارى تحليل الزوج...")


# ===============================
#  Flask Route for Webhook
# ===============================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    application.update_queue.put_nowait(data)
    return "ok"


# ===============================
#  Setup bot + webhook activation
# ===============================
application = Application.builder().token(TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("ideas", ideas))
application.add_handler(CommandHandler("analysis", analysis))


if __name__ == "__main__":
    # Set webhook
    requests.get(
        f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={WEBHOOK_URL}/webhook"
    )

    # Run Flask server
    app.run(host="0.0.0.0", port=8080)
