# config.py
import os
import logging
from collections import deque

import requests

# ==============================
#      قراءة متغيرات البيئة
# ==============================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TELELEGRAM_TOKEN:
    raise RuntimeError("البيئة لا تحتوى على TELEGRAM_TOKEN")

APP_BASE_URL = os.environ.get("APP_BASE_URL")
if not APP_BASE_URL:
    raise RuntimeError("البيئة لا تحتوى على APP_BASE_URL")

# ID شات الأدمن (يبقى رقم التيليجرام بتاعك)
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0") or "0")
if not ADMIN_CHAT_ID:
    raise RuntimeError("البيئة لا تحتوى على ADMIN_CHAT_ID (رقم شات الأدمن)")

# توكن بسيط لحماية لوحة التحكم (تستخدمه فى ?pass=)
ADMIN_DASHBOARD_TOKEN = os.environ.get("ADMIN_DASHBOARD_TOKEN", "")

# وضع الديباج
BOT_DEBUG = os.environ.get("BOT_DEBUG", "0") == "1"

# ==============================
#           Logging
# ==============================

logger = logging.getLogger("incrypto-bot")
logger.setLevel(logging.DEBUG if BOT_DEBUG else logging.INFO)

_handler = logging.StreamHandler()
_handler.setFormatter(
    logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s", "%Y-%m-%d %H:%M:%S"
    )
)
logger.addHandler(_handler)

# ==============================
#     Telegram HTTP Session
# ==============================

HTTP_SESSION = requests.Session()
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ==============================
#      كاش + حالة النظام
# ==============================

# كاش تحليلات / Dashboard
REALTIME_CACHE = {
    "btc_analysis": None,
    "market_report": None,
    "risk_test": None,
    "weekly_report": None,
    "alert_text": None,
    "weekly_built_at": 0.0,
    "alert_built_at": 0.0,
    "last_update": 0.0,
}

# كاش بيانات السوق الخام (BTCUSDT)
MARKET_METRICS_CACHE = {
    "data": None,
    "ts": 0.0,
}

# زمن صلاحية الكاش (ثوانى)
REALTIME_TTL_SECONDS = int(os.environ.get("REALTIME_TTL_SECONDS", "20"))
MARKET_METRICS_TTL_SECONDS = int(os.environ.get("MARKET_METRICS_TTL_SECONDS", "10"))

# حالة مزودى البيانات
API_STATUS = {
    "binance_ok": True,
    "kucoin_ok": True,
    "last_api_check": None,
}

# سجل التحذيرات (للوحة التحكم)
ALERTS_HISTORY = deque(maxlen=200)

# شاتات البوت المعروفة
KNOWN_CHAT_IDS: set[int] = set()

# Ticks للمراقبة / مراقب التجمد
LAST_REALTIME_TICK: float | None = None
LAST_WEEKLY_TICK: float | None = None
LAST_WEBHOOK_TICK: float | None = None
LAST_WATCHDOG_TICK: float | None = None

LAST_ALERT_REASON: str | None = None
LAST_AUTO_ALERT_INFO: dict = {}
LAST_ERROR_INFO: dict | None = None
LAST_WEEKLY_SENT_DATE: str | None = None

# Buffer بسيط للّوج؛ عشان لوحة التحكم
_LOG_BUFFER = deque(maxlen=400)


# ==============================
#         دوال مساعدة
# ==============================

def _log_to_buffer(level: str, msg: str):
    try:
        _LOG_BUFFER.append(f"[{level}] {msg}")
    except Exception:
        pass


def log_cleaned_buffer() -> str:
    """يرجع نسخة Text من آخر اللوجات ليتم عرضها فى /admin/logs"""
    return "\n".join(_LOG_BUFFER)


# نلف ال logger عشان نسجل فى buffer برضه
class _BufferHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            _log_to_buffer(record.levelname, msg)
        except Exception:
            pass


_buffer_handler = _BufferHandler()
_buffer_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", "%H:%M:%S")
)
logger.addHandler(_buffer_handler)


# ==============================
#    Telegram Helper Functions
# ==============================

def send_message(chat_id: int, text: str, silent: bool = False):
    """إرسال رسالة تيليجرام عادية."""
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_notification": bool(silent),
        }
        r = HTTP_SESSION.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)
        if not r.ok:
            logger.warning("send_message failed: %s - %s", r.status_code, r.text)
        return r
    except Exception as e:
        logger.exception("send_message error: %s", e)


def send_message_with_keyboard(chat_id: int, text: str, keyboard: dict, silent: bool = False):
    """إرسال رسالة مع Inline Keyboard."""
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": keyboard,
            "disable_notification": bool(silent),
        }
        r = HTTP_SESSION.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)
        if not r.ok:
            logger.warning("send_message_with_keyboard failed: %s - %s", r.status_code, r.text)
        return r
    except Exception as e:
        logger.exception("send_message_with_keyboard error: %s", e)


def answer_callback_query(callback_query_id: str, text: str | None = None):
    """الرد على ضغط زر Inline."""
    try:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        r = HTTP_SESSION.post(f"{TELEGRAM_API}/answerCallbackQuery", json=payload, timeout=10)
        if not r.ok:
            logger.warning("answer_callback_query failed: %s - %s", r.status_code, r.text)
        return r
    except Exception as e:
        logger.exception("answer_callback_query error: %s", e)


def add_alert_history(source: str, reason: str, price: float | None = None, change: float | None = None):
    """إضافة عنصر لسجل التحذيرات (يظهر فى لوحة التحكم)."""
    from datetime import datetime

    item = {
        "time": datetime.utcnow().isoformat(timespec="seconds"),
        "source": source,
        "reason": reason,
    }
    if price is not None:
        item["price"] = float(price)
    if change is not None:
        item["change_pct"] = float(change)

    ALERTS_HISTORY.append(item)


# ==============================
#   صلاحية لوحة التحكم / Dashboard
# ==============================

def check_admin_auth(request) -> bool:
    """
    حماية بسيطة للوحة التحكم:
    - لو ADMIN_DASHBOARD_TOKEN فاضى → نسمح (للاستخدام الشخصى).
    - غير كده: لازم ?pass=TOKEN أو header X-Admin-Token.
    """
    if not ADMIN_DASHBOARD_TOKEN:
        return True

    q_pass = request.args.get("pass") or request.args.get("password")
    h_pass = request.headers.get("X-Admin-Token")

    if q_pass == ADMIN_DASHBOARD_TOKEN or h_pass == ADMIN_DASHBOARD_TOKEN:
        return True

    return False
