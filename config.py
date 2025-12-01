import os
import time
import logging
import requests
from datetime import datetime
from collections import deque
from flask import Request

# ==============================
#        الإعدادات العامة
# ==============================

# نقرأ من أى واحد من الاتنين حسب اللى موجود فى Koyeb
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
APP_BASE_URL = (
    os.getenv("APP_BASE_URL")
    or os.getenv("WEBHOOK_URL")
    or ""
).rstrip("/")

ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "669209875"))
ADMIN_DASH_PASSWORD = os.getenv("ADMIN_DASH_PASSWORD", "change_me")

# وضع الديبج
BOT_DEBUG = os.getenv("BOT_DEBUG", "0") == "1"

if not TELEGRAM_TOKEN:
    raise RuntimeError("❌ البيئة لا تحتوى على TELEGRAM_TOKEN أو BOT_TOKEN")

if not APP_BASE_URL:
    raise RuntimeError("❌ البيئة لا تحتوى على APP_BASE_URL أو WEBHOOK_URL")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ==============================
#        HTTP Session
# ==============================

HTTP_SESSION = requests.Session()

# ==============================
#   حالة النظام / الـ Watchdog
# ==============================

LAST_REALTIME_TICK = 0
LAST_WEEKLY_TICK = 0
LAST_WEBHOOK_TICK = 0
LAST_WATCHDOG_TICK = 0

# حالة آخر تحذير اتبعت تلقائى
LAST_ALERT_REASON: str | None = None

# آخر استدعاء لـ /auto_alert (للوحة المراقبة)
LAST_AUTO_ALERT_INFO: dict = {
    "time": None,
    "reason": None,
    "sent": False,
}

# آخر خطأ فى اللوج
LAST_ERROR_INFO: dict = {
    "time": None,
    "message": None,
}

# 🔁 آخر مرة تبعت فيها التقرير الأسبوعى أوتوماتيك (YYYY-MM-DD)
LAST_WEEKLY_SENT_DATE: str | None = None

# ==============================
#  إعداد اللوج + Log Buffer
# ==============================

LOG_BUFFER = deque(maxlen=300)  # آخر 300 سطر لوج

class InMemoryLogHandler(logging.Handler):
    def emit(self, record):
        global LAST_ERROR_INFO
        msg = self.format(record)
        LOG_BUFFER.append(msg)
        if record.levelno >= logging.ERROR:
            LAST_ERROR_INFO = {
                "time": datetime.utcnow().isoformat(timespec="seconds"),
                "message": msg,
            }

LOG_LEVEL = logging.DEBUG if BOT_DEBUG else logging.INFO

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("incrypto_bot")

_memory_handler = InMemoryLogHandler()
_memory_handler.setLevel(logging.INFO)
_memory_handler.setFormatter(
    logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
)
logger.addHandler(_memory_handler)

def log_cleaned_buffer() -> str:
    """إرجاع اللوج من الـ Buffer لعرضه فى /admin/logs."""
    return "\n".join(LOG_BUFFER)

# ==============================
#  الكاش + حالة الـ APIs
# ==============================

# كاش أسعار العملات (يستخدمه analysis_engine)
PRICE_CACHE: dict[str, dict] = {}
CACHE_TTL_SECONDS = 5  # ثوانى لكل سعر

# كاش قراءات السوق العامة للبيتكوين
MARKET_TTL_SECONDS = 10  # TTL للمقاييس
REALTIME_TTL_SECONDS = 10  # TTL للكاش العام

MARKET_METRICS_CACHE: dict = {
    "symbol": None,
    "price": None,
    "high": None,
    "low": None,
    "volume": None,
    "change_pct": None,
    "range_pct": None,
    "volatility_score": None,
    "rsi_est": None,
    "liquidity_pulse": None,
    "strength_label": None,
    "support_1": None,
    "resistance_1": None,
    "deep_support": None,
    "breakout_level": None,
    "ts": 0,
}

REALTIME_CACHE: dict = {
    "btc_analysis": None,
    "market_report": None,
    "risk_test": None,
    "alert_text": None,
    "weekly_report": None,
    "last_update": None,
}

API_STATUS: dict = {
    "binance_ok": True,
    "kucoin_ok": True,
    "binance_last_error": None,
    "kucoin_last_error": None,
    "last_api_check": None,
}

# ==============================
#   متابعة الشاتات
# ==============================

KNOWN_CHAT_IDS: set[int] = set()

# ==============================
#   سجل التحذيرات للأدمن
# ==============================

ALERTS_HISTORY = deque(maxlen=200)

def add_alert_history(
    source: str, reason: str,
    price: float | None = None,
    change: float | None = None,
):
    entry = {
        "time": datetime.utcnow().isoformat(timespec="seconds"),
        "source": source,
        "reason": reason,
        "price": price,
        "change_pct": change,
    }
    ALERTS_HISTORY.append(entry)
    logger.info("Alert history added: %s", entry)

# ==============================
#   دوال الإرسال لتليجرام
# ==============================

def _clean_text(text: str) -> str:
    # بس نضمن إنه String
    return text if isinstance(text, str) else str(text)

def send_message(chat_id: int | str, text: str, reply_markup=None):
    """إرسال رسالة عادية."""
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": _clean_text(text),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        r = HTTP_SESSION.post(url, json=payload, timeout=15)
        if r.status_code != 200:
            logger.warning(
                "Telegram sendMessage error: %s - %s",
                r.status_code,
                r.text,
            )
        return r
    except Exception as e:
        logger.exception("Exception while sending message: %s", e)

def send_message_with_keyboard(chat_id: int | str, text: str, keyboard: list[list[dict]]):
    """إرسال رسالة مع كيبورد إنلاين."""
    reply_markup = {"inline_keyboard": keyboard}
    return send_message(chat_id, text, reply_markup=reply_markup)

def answer_callback_query(
    callback_query_id: str,
    text: str | None = None,
    show_alert: bool = False,
):
    """إيقاف اللودنج لما المستخدم يضغط زر إنلاين."""
    try:
        url = f"{TELEGRAM_API}/answerCallbackQuery"
        payload = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }
        if text:
            payload["text"] = _clean_text(text)
        r = HTTP_SESSION.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            logger.warning(
                "Telegram answerCallbackQuery error: %s - %s",
                r.status_code,
                r.text,
            )
    except Exception as e:
        logger.exception("Exception while answering callback query: %s", e)

# ==============================
#   صلاحيات لوحة التحكم
# ==============================

def check_admin_auth(request: Request) -> bool:
    """
    تحقق بسيط:
    - من Query: ?token=XXX أو ?password=XXX
    - أو Header: X-Admin-Token: XXX
    لازم يطابق ADMIN_DASH_PASSWORD
    """
    token = (
        request.args.get("token")
        or request.args.get("password")
        or request.headers.get("X-Admin-Token")
    )
    if not ADMIN_DASH_PASSWORD:
        return False
    return token == ADMIN_DASH_PASSWORD
