import os
import time
import json
import logging
import threading
import requests
from datetime import datetime

# ============================
# إعداد اللوج — Logger
# ============================

logger = logging.getLogger("INCRYPTO_AI")
logger.setLevel(logging.INFO)

_formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

_handler = logging.StreamHandler()
_handler.setFormatter(_formatter)
logger.addHandler(_handler)

# حفظ آخر 500 سطر لوج للداشبورد
_LOG_BUFFER = []

def _push_log(line):
    if len(_LOG_BUFFER) >= 500:
        _LOG_BUFFER.pop(0)
    _LOG_BUFFER.append(line)

class BufferLogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        _push_log(msg)

logger.addHandler(BufferLogHandler())


def log_cleaned_buffer():
    return "\n".join(_LOG_BUFFER)


# ============================
# البيئة — ENV
# ============================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
APP_BASE_URL = os.getenv("APP_BASE_URL", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("البيئة لا تحتوى على BOT_TOKEN")
if ADMIN_CHAT_ID == 0:
    raise RuntimeError("البيئة لا تحتوى على ADMIN_CHAT_ID")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ============================
# HTTP Session
# ============================

HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({"User-Agent": "INCRYPTO_AI_BOT/1.0"})


# ============================
# Flags
# ============================
BOT_DEBUG = False

# ============================
# سجلات وحالة النظام
# ============================

KNOWN_CHAT_IDS = set()
ALERTS_HISTORY = []

LAST_ALERT_REASON = None
LAST_AUTO_ALERT_INFO = {"time": None, "reason": None, "sent": False}
LAST_ERROR_INFO = None
LAST_WEEKLY_SENT_DATE = None

LAST_REALTIME_TICK = None
LAST_WEEKLY_TICK = None
LAST_WEBHOOK_TICK = None
LAST_WATCHDOG_TICK = None

API_STATUS = {
    "binance_ok": True,
    "kucoin_ok": True,
    "last_api_check": None,
    "last_error": None,
}

REALTIME_CACHE = {"last_update": None}
MARKET_METRICS_CACHE = {}

# ============================
# Telegram Helpers
# ============================

def send_message(chat_id, text, silent=False):
    try:
        params = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_notification": silent,
        }
        r = HTTP_SESSION.get(f"{TELEGRAM_API}/sendMessage", params=params, timeout=10)
        return r.json()
    except Exception as e:
        logger.exception("send_message error: %s", e)


def send_message_with_keyboard(chat_id, text, keyboard):
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": json.dumps(keyboard, ensure_ascii=False),
        }
        r = HTTP_SESSION.post(f"{TELEGRAM_API}/sendMessage", data=payload, timeout=10)
        return r.json()
    except Exception as e:
        logger.exception("send_message_with_keyboard error: %s", e)


def answer_callback_query(callback_id):
    try:
        HTTP_SESSION.get(
            f"{TELEGRAM_API}/answerCallbackQuery",
            params={"callback_query_id": callback_id},
            timeout=10,
        )
    except Exception as e:
        logger.exception("answer_callback_query error: %s", e)


# ============================
#   Alert History
# ============================

def add_alert_history(source, reason, price=None, change=None):
    ALERTS_HISTORY.append(
        {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "source": source,
            "reason": reason,
            "price": price,
            "change": change,
        }
    )
    # نخلى العدد مايزدش عن 200
    if len(ALERTS_HISTORY) > 200:
        ALERTS_HISTORY.pop(0)


# ============================
#   Auth Checker للوحة التحكم
# ============================

def check_admin_auth(req):
    token = req.args.get("token") or req.headers.get("X-Admin-Token")
    return str(token) == str(ADMIN_CHAT_ID)
