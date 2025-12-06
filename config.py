import os
import time
import logging
import requests
from datetime import datetime
from collections import deque

# ==============================
#        الإعدادات العامة
# ==============================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
APP_BASE_URL = (os.getenv("APP_BASE_URL") or "").rstrip("/")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "669209875"))

ALERT_TARGET_CHAT_ID = int(os.getenv("ALERT_TARGET_CHAT_ID", str(ADMIN_CHAT_ID)))

ADMIN_DASH_PASSWORD = os.getenv("ADMIN_DASH_PASSWORD", "change_me")
BOT_DEBUG = os.getenv("BOT_DEBUG", "0") == "1"

if not TELEGRAM_TOKEN:
    raise RuntimeError("البيئة لا تحتوى على TELEGRAM_TOKEN")
if not APP_BASE_URL:
    raise RuntimeError("البيئة لا تحتوى على APP_BASE_URL")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ==============================
#  حالة التحذيرات / الأسبوعى
# ==============================

LAST_ALERT_REASON = None
LAST_AUTO_ALERT_INFO = {"time": None, "reason": None, "sent": False}

LAST_SMART_ALERT_INFO = {
    "time": None,
    "reason": None,
    "level": None,
    "shock_score": None,
    "risk_level": None,
    "sent_to": 0,
}

LAST_ERROR_INFO = {"time": None, "message": None}

LAST_WEEKLY_SENT_DATE = None
LAST_WEEKLY_RUN = None

# ==============================
#  إعداد اللوج + Log Buffer
# ==============================

LOG_BUFFER = deque(maxlen=300)

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

# ==============================
#  سجل تنبيهات الأدمن
# ==============================

ALERTS_HISTORY = deque(maxlen=100)

def add_alert_history(source, reason, price=None, change=None):
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
#  حفظ المستخدمين KNOWN_CHAT_IDS
# ==============================

USERS_FILE = "known_users.txt"

def load_known_users():
    """تحميل المستخدمين من الملف عند بدء التشغيل"""
    s = set()
    try:
        with open(USERS_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line.isdigit():
                    s.add(int(line))
        logger.info(f"Loaded {len(s)} known users from file.")
    except FileNotFoundError:
        logger.warning("No known_users.txt found — starting fresh.")
    except Exception as e:
        logger.exception(f"Failed loading users: {e}")
    return s

def save_known_users():
    """حفظ المستخدمين فى الملف"""
    try:
        with open(USERS_FILE, "w") as f:
            for uid in KNOWN_CHAT_IDS:
                f.write(f"{uid}\n")
        logger.info(f"Saved {len(KNOWN_CHAT_IDS)} users to file.")
    except Exception as e:
        logger.exception(f"Failed saving users: {e}")

KNOWN_CHAT_IDS = load_known_users()
KNOWN_CHAT_IDS.add(ADMIN_CHAT_ID)

# ==============================
#  HTTP Session
# ==============================

HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({"User-Agent": "InCryptoAI-Bot/1.0"})

# ==============================
#   كاش الأسعار + بيانات السوق
# ==============================

PRICE_CACHE = {}
CACHE_TTL_SECONDS = 5

MARKET_METRICS_CACHE = {"data": None, "time": 0.0}
MARKET_TTL_SECONDS = 4

PULSE_HISTORY = deque(maxlen=30)

# ==============================
#   Real-Time Cache
# ==============================

REALTIME_CACHE = {
    "btc_analysis": None,
    "market_report": None,
    "risk_test": None,
    "weekly_report": None,
    "alert_text": None,
    "last_update": None,
    "weekly_built_at": 0.0,
    "alert_built_at": 0.0,
}
REALTIME_TTL_SECONDS = 8

# ==============================
#   Watchdog
# ==============================

LAST_REALTIME_TICK = 0.0
LAST_WEEKLY_TICK = 0.0
LAST_WATCHDOG_TICK = 0.0
LAST_WEBHOOK_TICK = 0.0
LAST_SMART_ALERT_TICK = 0.0

API_STATUS = {
    "binance_ok": True,
    "binance_last_error": None,
    "kucoin_ok": True,
    "kucoin_last_error": None,
    "last_api_check": None,
}

# ==============================
#   Smart Alert Settings
# ==============================

SMART_ALERT_MIN_INTERVAL = 1.0
SMART_ALERT_MAX_INTERVAL = 4.0
SMART_ALERT_BASE_INTERVAL = 1.0

LAST_SMART_ALERT_TS = 0.0
LAST_CRITICAL_ALERT_TS = 0.0

EARLY_WARNING_THRESHOLD = 70.0

ALERT_HISTORY = deque(maxlen=200)

# ==============================
#  Telegram Send Functions
# ==============================

def send_message(chat_id, text, parse_mode="HTML", silent=False):
    try:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if silent:
            payload["disable_notification"] = True

        r = HTTP_SESSION.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)
        if r.status_code != 200:
            logger.warning(f"Telegram sendMessage error: {r.status_code} - {r.text}")
    except Exception as e:
        logger.exception("send_message error: %s", e)

def send_message_with_keyboard(chat_id, text, reply_markup, parse_mode="HTML", silent=False):
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        }
        if silent:
            payload["disable_notification"] = True

        r = HTTP_SESSION.post(
            f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10
        )
        if r.status_code != 200:
            logger.warning(f"sendMessage_with_keyboard error: {r.status_code} - {r.text}")
    except Exception as e:
        logger.exception("send_message_with_keyboard error: %s", e)

def answer_callback_query(callback_query_id, text=None, show_alert=False):
    try:
        payload = {"callback_query_id": callback_query_id, "show_alert": show_alert}
        if text:
            payload["text"] = text
        HTTP_SESSION.post(f"{TELEGRAM_API}/answerCallbackQuery", json=payload, timeout=10)
    except Exception as e:
        logger.exception("answer_callback_query error: %s", e)

def log_cleaned_buffer():
    lines = list(LOG_BUFFER)
    if not lines:
        return ""
    out = []
    last = None
    for line in lines:
        if line != last:
            out.append(line)
            last = line
    return "\n".join(out)

def check_admin_auth(req):
    return True

# ==============================
#   إعدادات Services
# ==============================

WEEKLY_REPORT_WEEKDAY = int(os.getenv("WEEKLY_REPORT_WEEKDAY", "6"))
WEEKLY_REPORT_HOUR_UTC = int(os.getenv("WEEKLY_REPORT_HOUR_UTC", "12"))

BOT = None

WATCHDOG_INTERVAL = float(os.getenv("WATCHDOG_INTERVAL", "5.0"))
REALTIME_ENGINE_INTERVAL = float(os.getenv("REALTIME_ENGINE_INTERVAL", "3.0"))

THREADS_STARTED = False

SNAPSHOT_FILE = os.getenv("SNAPSHOT_FILE")

BOT_TOKEN = os.getenv("BOT_TOKEN") or TELEGRAM_TOKEN

WEEKLY_REPORT_TTL = 3600

KEEP_ALIVE_URL = "https://dizzy-bab-incrypto-free-258377c4.koyeb.app/"
KEEP_ALIVE_INTERVAL = 240

# ==============================
#   Test Mode — Ultra PRO
# ==============================

FORCE_TEST_ULTRA_PRO = False
