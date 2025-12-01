import os
import logging
import requests
from collections import deque
from datetime import datetime

# ==============================
#         قراءة المتغيرات
# ==============================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
APP_BASE_URL = os.getenv("APP_BASE_URL")

if not TELEGRAM_TOKEN:
    raise RuntimeError("❌ البيئة لا تحتوى على TELEGRAM_TOKEN")

if not ADMIN_CHAT_ID:
    raise RuntimeError("❌ البيئة لا تحتوى على ADMIN_CHAT_ID")

if not APP_BASE_URL:
    raise RuntimeError("❌ البيئة لا تحتوى على APP_BASE_URL")

ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)

# ==============================
#        إعداد اللوج
# ==============================

logger = logging.getLogger("IN_CRYPTO_AI")
logger.setLevel(logging.INFO)

handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(handler)


# ==============================
#   ثوابت النظام
# ==============================

# مدة بقاء الكاش للردود
REALTIME_TTL_SECONDS = 8        # الكاش يعيش 8 ثوانى
MARKET_TTL_SECONDS   = 8

# Timeout لطلبات API
HTTP_TIMEOUT = 10

# ==============================
#   مخازن وذاكرة Runtime
# ==============================

HTTP_SESSION = requests.Session()

REALTIME_CACHE = {
    "last_update": None,
    "btc_analysis": None,
    "market_report": None,
    "risk_test": None,
    "alert_text": None,
    "weekly_report": None,
    "weekly_built_at": None,
    "alert_built_at": None,
}

MARKET_METRICS_CACHE = {}   # لكل عملة

ALERTS_HISTORY = deque(maxlen=100)

API_STATUS = {
    "binance_ok": True,
    "kucoin_ok": True,
    "last_api_check": None,
}

# ==============================
#     مؤشرات التشغيل / Ticks
# ==============================

LAST_REALTIME_TICK = 0
LAST_WEEKLY_TICK = 0
LAST_WEBHOOK_TICK = 0
LAST_WATCHDOG_TICK = 0

LAST_ALERT_REASON = None
LAST_AUTO_ALERT_INFO = {}
LAST_WEEKLY_SENT_DATE = None
LAST_ERROR_INFO = {}

KNOWN_CHAT_IDS = set()


# ==============================
#   دوال إرسال الرسائل
# ==============================

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def send_message(chat_id, text, silent=False):
    """إرسال رسالة عادية"""
    try:
        params = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_notification": silent,
        }
        r = HTTP_SESSION.get(f"{TELEGRAM_API}/sendMessage", params=params, timeout=HTTP_TIMEOUT)
        return r.json()
    except Exception as e:
        logger.exception("send_message error: %s", e)


def send_message_with_keyboard(chat_id, text, keyboard):
    """رسالة مع Inline Keyboard"""
    try:
        params = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": keyboard,
        }
        r = HTTP_SESSION.get(f"{TELEGRAM_API}/sendMessage", params=params, timeout=HTTP_TIMEOUT)
        return r.json()
    except Exception as e:
        logger.exception("send_message_with_keyboard error: %s", e)


def answer_callback_query(callback_id):
    """للرد على ضغط الأزرار"""
    try:
        HTTP_SESSION.get(
            f"{TELEGRAM_API}/answerCallbackQuery",
            params={"callback_query_id": callback_id},
            timeout=HTTP_TIMEOUT,
        )
    except Exception as e:
        logger.exception("answer_callback_query error: %s", e)


# ==============================
#      سجل التحذيرات
# ==============================

def add_alert_history(source, reason, price=None, change=None):
    ALERTS_HISTORY.appendleft(
        {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "source": source,
            "reason": reason,
            "price": price,
            "change": change,
        }
    )


# ==============================
#         Dashboard Auth
# ==============================

def check_admin_auth(request):
    """لوحة التحكم — لازم هيدر X-Admin-Key = ADMIN_CHAT_ID"""
    key = request.headers.get("X-Admin-Key")
    return key == str(ADMIN_CHAT_ID)


# ==============================
#   لوج نظيف للوحة التحكم
# ==============================

_log_buffer = deque(maxlen=500)

class _BufferHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        _log_buffer.append(msg)

buffer_handler = _BufferHandler()
buffer_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(buffer_handler)


def log_cleaned_buffer():
    return "\n".join(_log_buffer)
