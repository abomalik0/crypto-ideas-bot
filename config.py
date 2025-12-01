import os
import json
import logging
import requests
from datetime import datetime, timezone

# ============================
#   إعداد اللوجر
# ============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("INCRYPTO-BOT")

# ============================
#   المتغيرات البيئية
# ============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

if not BOT_TOKEN:
    raise RuntimeError("البيئة لا تحتوى على BOT_TOKEN")

if not WEBHOOK_URL:
    logger.warning("⚠️ لا يوجد WEBHOOK_URL فى البيئة!")

# وضع الديباج
BOT_DEBUG = False  # ← مهم للبوت.py

# ============================
#   جلسة HTTP واحدة سريعة
# ============================
HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({"User-Agent": "INCRYPTO-BOT/1.0"})

# ============================
#   كاش السوق
# ============================
MARKET_METRICS_CACHE = {
    "symbol": None,
    "ts": None
}
MARKET_TTL_SECONDS = 15  # ثانية

# ============================
#   حالة الـ API
# ============================
API_STATUS = {
    "binance_ok": True,
    "kucoin_ok": True,
    "last_api_check": None,
    "last_error": None,
}

# ============================
#   سجل التحذيرات لتجنب التكرار
# ============================
ALERT_HISTORY = {
    "last_reason": None,
    "last_ts": 0,
    "cooldown_seconds": 900,  # 15 دقيقة
}


def add_alert_history(reason: str):
    """تسجيل آخر تنبيه لتجنب الإرسال المكرر"""
    ALERT_HISTORY["last_reason"] = reason
    ALERT_HISTORY["last_ts"] = datetime.now(timezone.utc).timestamp()


# ============================
#   إرسال رسالة عادية
# ============================
def send_message(chat_id, text, parse_mode="HTML"):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = HTTP_SESSION.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }, timeout=10)
        return r.json()
    except Exception as e:
        logger.error(f"خطأ فى send_message: {e}")
        return None


# ============================
#   إرسال رسالة + كيبوورد
# ============================
def send_message_with_keyboard(chat_id, text, keyboard, parse_mode="HTML"):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "reply_markup": json.dumps(keyboard)
    }
    try:
        r = HTTP_SESSION.post(url, json=payload, timeout=10)
        return r.json()
    except Exception as e:
        logger.error(f"send_message_with_keyboard ERROR: {e}")
        return None


# ============================
#   الرد على ضغط زر (Callback)
# ============================
def answer_callback_query(callback_id, text=None, show_alert=False):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = True
    try:
        return HTTP_SESSION.post(url, json=payload, timeout=10).json()
    except Exception as e:
        logger.error(f"Callback error: {e}")
        return None


# ============================
#   إرسال Webhook عند التشغيل
# ============================
def set_webhook():
    if not WEBHOOK_URL:
        logger.warning("⚠️ لم يتم ضبط WEBHOOK_URL — البوت سيعمل بدون Webhook")
        return None

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    try:
        r = HTTP_SESSION.post(url, json={"url": WEBHOOK_URL}, timeout=10)
        logger.info(f"Webhook response: {r.status_code} - {r.text}")
        return r.json()
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return None
