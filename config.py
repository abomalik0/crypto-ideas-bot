import os
import logging
import requests
from datetime import datetime

# ============================
#   LOGGER
# ============================

logger = logging.getLogger("INCRYPTO")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(handler)


# ============================
#   ENV VARIABLES
# ============================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN:
    raise RuntimeError("البيئة لا تحتوي على BOT_TOKEN")

if not ADMIN_CHAT_ID:
    raise RuntimeError("البيئة لا تحتوي على ADMIN_CHAT_ID")

if not WEBHOOK_URL:
    raise RuntimeError("البيئة لا تحتوي على WEBHOOK_URL")


# ============================
#   API & HTTP SESSION
# ============================

HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({"User-Agent": "INCRYPTO-AI-BOT/1.0"})


# ============================
#   CACHE & TIMING CONFIG
# ============================

# مدة صلاحية بيانات السوق قبل إعادة التحديث
MARKET_TTL_SECONDS = 25   # يجب أن تكون موجودة (حل الخطأ)

# مدة التحديث اللحظي لمحرك الذكاء الاصطناعي
REALTIME_TTL_SECONDS = 10

# كاش بيانات السوق
MARKET_METRICS_CACHE = {}

# سجل آخر تحذيرات تم إرسالها
ALERT_HISTORY = []

# حاله API
API_STATUS = {
    "binance_ok": True,
    "kucoin_ok": True,
    "last_api_check": None,
    "last_error": None,
}


# ============================
#   TELEGRAM HELPERS
# ============================

def tg_send_message(chat_id, text, parse="HTML"):
    """إرسال رسالة تلغرام عادية"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = HTTP_SESSION.post(url, data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse
        }, timeout=5)
        return r.json()
    except Exception as e:
        logger.error(f"Telegram sendMessage error: {e}")
        return None


def send_message_with_keyboard(chat_id, text, keyboard):
    """إرسال رسالة مع أزرار Inline"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = HTTP_SESSION.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {"inline_keyboard": keyboard},
        }, timeout=5)
        return r.json()
    except Exception as e:
        logger.error(f"Keyboard send error: {e}")
        return None


def answer_callback_query(callback_id, text=None):
    """الرد على زر تم الضغط عليه"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    try:
        HTTP_SESSION.post(url, data={
            "callback_query_id": callback_id,
            "text": text or "",
            "show_alert": False
        }, timeout=4)
    except Exception as e:
        logger.error(f"Callback error: {e}")


# ============================
#   ADMIN / AUTH
# ============================

def check_admin_auth(chat_id):
    """تأكيد أن المستخدم هو الأدمن"""
    return str(chat_id) == str(ADMIN_CHAT_ID)


# ============================
#   ALERT HISTORY CONTROL
# ============================

def add_alert_history(reason: str):
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    ALERT_HISTORY.append({"reason": reason, "time": timestamp})


def log_cleaned_buffer():
    """إرجاع لوج مبسط للحفظ"""
    if len(ALERT_HISTORY) == 0:
        return "لا يوجد تحذيرات محفوظة."

    return "\n".join(f"{a['time']} - {a['reason']}" for a in ALERT_HISTORY[-20:])
