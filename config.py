import os
import requests
import logging
import json
from datetime import datetime, timezone

# ============================
#     Logging system
# ============================

logger = logging.getLogger("crypto-ai-bot")
logger.setLevel(logging.INFO)

handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(handler)

# ============================
#     Environment Variables
# ============================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN:
    raise RuntimeError("البيئة لا تحتوى على BOT_TOKEN")

if not ADMIN_CHAT_ID:
    raise RuntimeError("البيئة لا تحتوى على ADMIN_CHAT_ID")

if not WEBHOOK_URL:
    raise RuntimeError("البيئة لا تحتوى على WEBHOOK_URL")

ADMIN_CHAT_ID = str(ADMIN_CHAT_ID)

# ============================
#     Telegram API Base
# ============================

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

HTTP_SESSION = requests.Session()

def send_message(chat_id, text, reply_markup=None):
    """إرسال رسالة عادية"""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    r = HTTP_SESSION.post(f"{TG_API}/sendMessage", json=payload)
    return r.json()


def send_message_with_keyboard(chat_id, text, buttons):
    """إرسال رسالة مع كيبورد تحت"""
    keyboard = {"inline_keyboard": buttons}
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": keyboard
    }
    r = HTTP_SESSION.post(f"{TG_API}/sendMessage", json=payload)
    return r.json()


def answer_callback_query(callback_id, text=None):
    """الرد على زر مضغوط"""
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text

    return HTTP_SESSION.post(f"{TG_API}/answerCallbackQuery", json=payload).json()

# ============================
#     Alert History
# ============================

ALERT_HISTORY = []

def add_alert_history(reason: str, data: dict):
    """حفظ سجل التحذيرات"""
    ALERT_HISTORY.append({
        "reason": reason,
        "data": data,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")
    })
    # حفظ آخر 50 فقط
    if len(ALERT_HISTORY) > 50:
        ALERT_HISTORY.pop(0)

# ============================
#     Log buffer system
# ============================

LOG_BUFFER = []

def log_cleaned_buffer(message: str):
    """يسجل رسائل نظيفة لأغراض الديباج"""
    try:
        LOG_BUFFER.append({
            "message": message,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")
        })
        if len(LOG_BUFFER) > 50:
            LOG_BUFFER.pop(0)
    except Exception as e:
        logger.error(f"log_cleaned_buffer error: {e}")

# ============================
#   API STATUS
# ============================

API_STATUS = {
    "binance_ok": True,
    "kucoin_ok": True,
    "last_api_check": None,
    "last_error": None
}

# ============================
#   MARKET CACHE
# ============================

MARKET_METRICS_CACHE = {}
MARKET_TTL_SECONDS = 10  # cache for metrics

# ============================
#   Bot flags
# ============================

BOT_DEBUG = False   # إذا True يعرض رسائل إضافية

# ============================
#   Utility helpers
# ============================

def notify_admin(text):
    """إرسال رسالة للإدمن"""
    try:
        send_message(ADMIN_CHAT_ID, text)
    except Exception as e:
        logger.error(f"notify_admin error: {e}")
