import os
import time
import logging
from logging.handlers import RotatingFileHandler
from collections import deque
import requests
from flask import Request

# ============================================
#               إعدادات أساسية
# ============================================

BOT_DEBUG = bool(int(os.getenv("BOT_DEBUG", "0")))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

if not TELEGRAM_TOKEN:
    raise RuntimeError("❌ البيئة لا تحتوي على TELEGRAM_TOKEN")

if not ADMIN_CHAT_ID:
    raise RuntimeError("❌ البيئة لا تحتوي على ADMIN_CHAT_ID (رقم شات الأدمن)")

ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)

APP_BASE_URL = os.getenv("APP_BASE_URL")
if not APP_BASE_URL:
    raise RuntimeError("❌ يجب تعيين APP_BASE_URL فى متغيرات البيئة")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ============================================
#                 إعدادات الكاش
# ============================================

REALTIME_CACHE = {
    "btc_analysis": None,
    "market_report": None,
    "risk_test": None,
    "alert_text": None,
    "weekly_report": None,
    "last_update": None,
}

# تحديث بيانات السوق كل عدد ثوانى
REALTIME_TTL_SECONDS = 10  # لتسريع التحليل

# تحديث بيانات الماركت (تحليل المؤشرات)
MARKET_TTL_SECONDS = 10

MARKET_METRICS_CACHE = {
    "symbol": None,
    "price": None,
    "change_pct": None,
    "range_pct": None,
    "volatility_score": None,
    "strength_label": None,
    "liquidity_pulse": None,
    "ts": 0,
}

# ============================================
#          متابعة الشات المستخدم
# ============================================

KNOWN_CHAT_IDS = set()

# ============================================
#       حالة الأنظمة – Watchdog Tracking
# ============================================

LAST_REALTIME_TICK = 0
LAST_WEEKLY_TICK = 0
LAST_WEBHOOK_TICK = 0
LAST_WATCHDOG_TICK = 0

LAST_ALERT_REASON = None
LAST_AUTO_ALERT_INFO = {}
LAST_ERROR_INFO = {}
LAST_WEEKLY_SENT_DATE = None

# ============================================
#               الـ Alerts History
# ============================================

ALERTS_HISTORY = deque(maxlen=200)

def add_alert_history(source, reason, price=None, change=None):
    entry = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "source": source,
        "reason": reason,
        "price": price,
        "change": change,
    }
    ALERTS_HISTORY.append(entry)

def log_cleaned_buffer():
    """لوج نظيف للعرض فى لوحة التحكم"""
    try:
        with open("runtime.log", "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "(no logs)"

# ============================================
#           Logging System (احترافى)
# ============================================

logger = logging.getLogger("crypto-ai")
logger.setLevel(logging.INFO)

handler = RotatingFileHandler("runtime.log", maxBytes=500_000, backupCount=3, encoding="utf-8")
formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s",
    "%Y-%m-%d %H:%M:%S"
)
handler.setFormatter(formatter)
logger.addHandler(handler)

# ============================================
#                HTTP SESSION
# ============================================

HTTP_SESSION = requests.Session()

# ============================================
#        Telegram Sender Functions
# ============================================

def send_message(chat_id, text, silent=False):
    """إرسال رسالة تيليجرام"""
    try:
        params = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_notification": silent,
        }
        HTTP_SESSION.get(f"{TELEGRAM_API}/sendMessage", params=params, timeout=10)
    except Exception as e:
        logger.exception("Send message error: %s", e)


def send_message_with_keyboard(chat_id, text, keyboard):
    """إرسال رسالة مع Inline Keyboard"""
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": keyboard,
        }
        HTTP_SESSION.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logger.exception("Send keyboard error: %s", e)


def answer_callback_query(callback_id):
    try:
        HTTP_SESSION.post(
            f"{TELEGRAM_API}/answerCallbackQuery",
            json={"callback_query_id": callback_id},
            timeout=10,
        )
    except Exception as e:
        logger.exception("CallbackQuery error: %s", e)

# ============================================
#     Admin Dashboard Authentication Helper
# ============================================

def check_admin_auth(request: Request):
    token = request.args.get("token") or request.headers.get("X-Admin-Token")
    return token == str(ADMIN_CHAT_ID)
