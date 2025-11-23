import os
import logging
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# ============================
# إعدادات اللوج
# ============================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================
# تحميل التوكن من Environment
# ============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not found in environment variables!")

# ============================
# FastAPI App
# ============================
app = FastAPI()

# ============================
# Telegram App بدون أي Loop
# ============================
telegram_app = Application.builder().token(BOT_TOKEN).build()

# ============================
# أوامر البوت
# ============================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("البوت شغال تمام ✔️")

async def ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("جارِ جلب الأفكار…")

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("ideas", ideas))

# ============================
# Webhook Endpoint
# ============================
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

# ============================
# Root
# ============================
@app.get("/")
async def home():
    return {"status": "Bot is running on Koyeb Webhook!"}
