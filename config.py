import os
import time
import logging
import requests
import json
from datetime import datetime
from collections import deque

# ==============================
#        الإعدادات العامة
# ==============================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
APP_BASE_URL = (os.getenv("APP_BASE_URL") or "").rstrip("/")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "669209875"))

# الجروب / القناة اللى هتستقبل التحذيرات للمستخدمين
ALERT_TARGET_CHAT_ID = int(os.getenv("ALERT_TARGET_CHAT_ID", str(ADMIN_CHAT_ID)))

ADMIN_DASH_PASSWORD = os.getenv("ADMIN_DASH_PASSWORD", "change_me")
BOT_DEBUG = os.getenv("BOT_DEBUG", "0") == "1"

if not TELEGRAM_TOKEN:
    raise RuntimeError("البيئة لا تحتوى على TELEGRAM_TOKEN")

if not APP_BASE_URL:
    raise RuntimeError("البيئة لا تحتوى على APP_BASE_URL")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# قاعدة مجلد البيانات (لحفظ known_chats.json)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except Exception:
    # فى حالة أى خطأ فى إنشاء المجلد، نكمل عادى بدون كسر البوت
    pass

KNOWN_CHATS_FILE = os.path.join(DATA_DIR, "known_chats.json")

# ==============================
#  حالة التحذيرات / الأسبوعى
# ==============================

# حالة آخر تحذير اتبعت تلقائى (النظام القديم /auto_alert)
LAST_ALERT_REASON: str | None = None

# آخر استدعاء لـ /auto_alert (للوحة المراقبة)
LAST_AUTO_ALERT_INFO: dict = {
    "time": None,
    "reason": None,
    "sent": False,
}

# آخر حالة للتحذير الذكى (Smart Trigger المتطور)
LAST_SMART_ALERT_INFO: dict = {
    "time": None,
    "reason": None,       # وصف السبب (منطق الأحداث الذكية)
    "level": None,        # low / medium / high / critical
    "shock_score": None,  # 0–100 تقدير عنف الحركة
    "risk_level": None,   # low / medium / high
    "sent_to": 0,         # عدد الشاتات التى استقبلت آخر تحذير
    "sent_to_count": 0,
}

# آخر خطأ فى اللوج (يتحدث تلقائياً)
LAST_ERROR_INFO: dict = {
    "time": None,
    "message": None,
}

# 🔁 آخر مرة تبعت فيها التقرير الأسبوعى أوتوماتيك (YYYY-MM-DD)
LAST_WEEKLY_SENT_DATE: str | None = None

# آخر مرة اتنفّذ فيها الـ weekly scheduler (قيمته تُحدَّث فى services)
LAST_WEEKLY_RUN = None

# ==============================
#  إعداد اللوج + Log Buffer للـ Dashboard
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

# ==============================
#  تخزين تاريخ التحذيرات للأدمن
# ==============================

ALERTS_HISTORY = deque(maxlen=100)

def add_alert_history(
    source: str, reason: str, price: float | None = None, change: float | None = None
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
#   قائمة بالشاتات المعروفة (مع حفظ على ملف)
# ==============================

# كل مستخدم استخدم البوت مرة واحدة على الأقل
KNOWN_CHAT_IDS: set[int] = set()
KNOWN_CHAT_IDS.add(ADMIN_CHAT_ID)

def _save_known_chats():
    """
    حفظ KNOWN_CHAT_IDS فى ملف JSON داخل /data/known_chats.json
    """
    try:
        # نحول الـ set لقائمة مرتبة علشان تكون مقروءة
        data = sorted(int(cid) for cid in KNOWN_CHAT_IDS)
        with open(KNOWN_CHATS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        logger.info("Saved %d known chat ids to %s", len(data), KNOWN_CHATS_FILE)
    except Exception as e:
        logger.exception("Error saving known chats: %s", e)

def _load_known_chats():
    """
    تحميل الشاتات المعروفة من known_chats.json (لو موجود).
    """
    global KNOWN_CHAT_IDS
    try:
        if os.path.exists(KNOWN_CHATS_FILE):
            with open(KNOWN_CHATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for cid in data:
                    try:
                        KNOWN_CHAT_IDS.add(int(cid))
                    except Exception:
                        continue
            elif isinstance(data, dict):
                # لو اتخزن dict بالخطأ فى أى وقت، نجرب ناخد القيم
                for cid in data.values():
                    try:
                        KNOWN_CHAT_IDS.add(int(cid))
                    except Exception:
                        continue
            logger.info(
                "Loaded %d known chat ids from %s",
                len(KNOWN_CHAT_IDS),
                KNOWN_CHATS_FILE,
            )
    except Exception as e:
        logger.exception("Error loading known chats: %s", e)
    finally:
        # نتأكد دايمًا إن الـ ADMIN_CHAT_ID موجود
        KNOWN_CHAT_IDS.add(ADMIN_CHAT_ID)

def register_known_chat(chat_id: int):
    """
    تسجيل أى chat_id جديد فى KNOWN_CHAT_IDS + حفظه فوراً على الملف.
    - لو الشات مسجل قبل كده → مفيش أى حفظ إضافى (مافيش Spam على الـ I/O).
    """
    try:
        chat_id = int(chat_id)
    except Exception:
        return
    try:
        if chat_id not in KNOWN_CHAT_IDS:
            KNOWN_CHAT_IDS.add(chat_id)
            _save_known_chats()
            logger.info(
                "Registered new chat_id=%s (total_known=%d)",
                chat_id,
                len(KNOWN_CHAT_IDS),
            )
    except Exception as e:
        logger.exception("Error registering known chat %s: %s", chat_id, e)

# تحميل الشاتات من الملف عند أول استيراد لـ config
try:
    _load_known_chats()
except Exception as e:
    logger.exception("Failed to load known chats on startup: %s", e)

# ==============================
#   HTTP Session موحدة
# ==============================

HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update(
    {
        "User-Agent": "InCryptoAI-Bot/1.0",
    }
)

# ==============================
#   كاش الأسعار + متركس السوق
# ==============================

PRICE_CACHE: dict[str, dict] = {}
CACHE_TTL_SECONDS = 5  # للكروت القصيرة (ثوانٍ)

MARKET_METRICS_CACHE: dict = {
    "data": None,
    "time": 0.0,
}
MARKET_TTL_SECONDS = 4  # ثوانى

# ------------------------------
#   Pulse History (Smart Engine)
# ------------------------------
PULSE_HISTORY = deque(maxlen=30)

# ==============================
#   Real-Time Cache (نصوص جاهزة)
# ==============================

REALTIME_CACHE: dict = {
    "btc_analysis": None,
    "market_report": None,
    "risk_test": None,
    "weekly_report": None,
    "alert_text": None,
    "last_update": None,
    "weekly_built_at": 0.0,
    "alert_built_at": 0.0,
}
REALTIME_TTL_SECONDS = 8  # ثوانى

# ==============================
#   Watchdog / Health Indicators
# ==============================

LAST_REALTIME_TICK: float = 0.0
LAST_WEEKLY_TICK: float = 0.0
LAST_WATCHDOG_TICK: float = 0.0
LAST_WEBHOOK_TICK: float = 0.0
LAST_SMART_ALERT_TICK: float = 0.0
LAST_KEEP_ALIVE_TICK: float = 0.0
LAST_KEEP_ALIVE_OK: float = 0.0

API_STATUS: dict = {
    "binance_ok": True,
    "binance_last_error": None,
    "kucoin_ok": True,
    "kucoin_last_error": None,
    "last_api_check": None,
}

# ==============================
#  إعدادات نظام التنبيه الذكى
# ==============================

# الفاصل الأدنى والأقصى (بالثوانى) لو أردت استخدامه مستقبلاً
SMART_ALERT_MIN_INTERVAL: float = 1.0   # ثانية (للاندفاع الحاد)
SMART_ALERT_MAX_INTERVAL: float = 4.0   # ثانية (للسوق الهادئ)

# الفاصل الأساسى للـ Smart Alert (بالدقائق) – بيُستخدم داخل smart_alert_loop
SMART_ALERT_BASE_INTERVAL: float = 1.0

# زمن آخر تنبيه من الذكى
LAST_SMART_ALERT_TS: float = 0.0
LAST_CRITICAL_ALERT_TS: float = 0.0

# Threshold للإنذار المبكر
EARLY_WARNING_THRESHOLD: float = 70.0

# سجل تنبيهات الذكى (يختلف عن ALERTS_HISTORY العام)
ALERT_HISTORY = deque(maxlen=200)

# ==============================
#  كاش الردود النصية العامة
# ==============================

RESPONSE_CACHE: dict = {}
DEFAULT_RESPONSE_TTL: float = 10.0  # ثوانى

# ==============================
#  Telegram Helpers (+ Silent Alert)
# ==============================

def send_message(
    chat_id: int,
    text: str,
    parse_mode: str = "HTML",
    silent: bool = False,
):
    """إرسال رسالة عادية مع خيار الإشعار الصامت."""
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        payload: dict = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if silent:
            payload["disable_notification"] = True

        r = HTTP_SESSION.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            logger.warning(
                "Telegram sendMessage error: %s - %s",
                r.status_code,
                r.text,
            )
    except Exception as e:
        logger.exception("Exception while sending message: %s", e)


def send_message_with_keyboard(
    chat_id: int,
    text: str,
    reply_markup: dict,
    parse_mode: str = "HTML",
    silent: bool = False,
):
    """إرسال رسالة مع كيبورد إنلاين."""
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        payload: dict = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        }
        if silent:
            payload["disable_notification"] = True

        r = HTTP_SESSION.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            logger.warning(
                "Telegram sendMessage_with_keyboard error: %s - %s",
                r.status_code,
                r.text,
            )
    except Exception as e:
        logger.exception("Exception while sending message with keyboard: %s", e)


def answer_callback_query(
    callback_query_id: str,
    text: str | None = None,
    show_alert: bool = False,
):
    """الرد على ضغط زر إنلاين عشان يوقف اللودنج."""
    try:
        url = f"{TELEGRAM_API}/answerCallbackQuery"
        payload: dict = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }
        if text:
            payload["text"] = text
        r = HTTP_SESSION.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            logger.warning(
                "Telegram answerCallbackQuery error: %s - %s",
                r.status_code,
                r.text,
            )
    except Exception as e:
        logger.exception("Exception while answering callback query: %s", e)


def log_cleaned_buffer() -> str:
    """
    ضغط اللوج:
    - يشيل التكرار المتتالى
    """
    lines = list(LOG_BUFFER)
    if not lines:
        return ""
    out: list[str] = []
    last = None
    for line in lines:
        if line != last:
            out.append(line)
            last = line
    return "\n".join(out)


def check_admin_auth(req) -> bool:
    """
    ممكن تضيف Basic Auth أو توكن أو مقارنة HEADER بالـ ADMIN_DASH_PASSWORD.
    دلوقتى راجع True (مفتوح).
    """
    # مثال لو حبيت:
    # pwd = req.headers.get("X-Admin-Password")
    # return pwd == ADMIN_DASH_PASSWORD
    return True

# ==============================
#  إعدادات إضافية لـ services.py
# ==============================

# يوم إرسال التقرير الأسبوعي (0 = الاثنين … 6 = الأحد)
WEEKLY_REPORT_WEEKDAY = int(os.getenv("WEEKLY_REPORT_WEEKDAY", "6"))  # الافتراض: الأحد

# ساعة إرسال التقرير الأسبوعى UTC
WEEKLY_REPORT_HOUR_UTC = int(os.getenv("WEEKLY_REPORT_HOUR_UTC", "12"))

# البوت الأساسي (يتم إنشاؤه فى services._ensure_bot)
BOT = None

# فترات عمل اللوپس
WATCHDOG_INTERVAL = float(os.getenv("WATCHDOG_INTERVAL", "5.0"))          # ثوانى
REALTIME_ENGINE_INTERVAL = float(os.getenv("REALTIME_ENGINE_INTERVAL", "3.0"))  # ثوانى

# لإيقاف تشغيل الـ threads مرة واحدة فقط
THREADS_STARTED = False

# ملف السناك شوت (اختيارى)
SNAPSHOT_FILE = os.getenv("SNAPSHOT_FILE")  # لو فاضى هيتجهل

# توكن البوت (نفس TELEGRAM_TOKEN أو متغير منفصل لو حبيت)
BOT_TOKEN = os.getenv("BOT_TOKEN") or TELEGRAM_TOKEN

# TTL للتقرير الأسبوعى فى الكاش (ثانية)
WEEKLY_REPORT_TTL = 3600

# إعدادات Keep-Alive لـ Koyeb
KEEP_ALIVE_URL = os.getenv(
    "KEEP_ALIVE_URL",
    "https://dizzy-bab-incrypto-free-258377c4.koyeb.app/",
)
KEEP_ALIVE_INTERVAL = int(os.getenv("KEEP_ALIVE_INTERVAL", "240"))   # كل 4 دقايق ping

# 🔥 Test Mode — لتجربة Ultra PRO من smart_alert_loop
# مهم: نخليها False فى التشغيل العادى علشان مايبعتش تحذير تجريبى بعد كل Restart
FORCE_TEST_ULTRA_PRO = False
