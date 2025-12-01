import os
import json
import logging
import requests
from datetime import datetime

# ==============================
#  الإعدادات العامة
# ==============================

# وضع الديباج
BOT_DEBUG = False   # غيّرها إلى True لو عايز تشوف اللوج داخل البوت

# قراءة التوكن من البيئة
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

if not TELEGRAM_TOKEN:
    raise RuntimeError("❌ البيئة لا تحتوي TELEGRAM_TOKEN")

if not ADMIN_CHAT_ID:
    raise RuntimeError("❌ البيئة لا تحتوي ADMIN_CHAT_ID")

ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)

# Webhook URL
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

# ==============================
#  HTTP Session
# ==============================
HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({"User-Agent": "IN-CRYPTO-AI/1.0"})

# ==============================
#  LOGGING
# ==============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("IN-CRYPTO")

# ==============================
#  كاش البيانات
# ==============================
MARKET_METRICS_CACHE = {}  # كاش بيانات السوق
REALTIME_CACHE = {}        # كاش الردود اللحظية

API_STATUS = {
    "binance_ok": True,
    "kucoin_ok": True,
    "last_api_check": None,
    "last_error": None,
}

# ==============================
#  الأزمنة
# ==============================

# زمن صلاحية بيانات السوق قبل إعادة الجلب
MARKET_TTL_SECONDS = 5          # البيانات تتجدد كل 5 ثوانى

# زمن صلاحية سرعة الاستجابة للكاش
REALTIME_TTL_SECONDS = 4        # الكاش اللحظى لكل رد

# ==============================
#  التحكم فى التحذيرات
# ==============================

# عدم تكرار نفس التحذير
LAST_ALERT_REASON = None
LAST_ALERT_SENT_AT = 0          # وقت آخر تحذير
ALERT_COOLDOWN_SECONDS = 300    # 5 دقائق كـ minimum

# Smart Trigger
SMART_ALERT_MIN = 5             # أقل مرة
SMART_ALERT_MAX = 20            # أعلى مرة
SMART_ALERT_STEP = 5            # الزيادة على حسب الخطورة

# شاتات المستخدمين
KNOWN_CHAT_IDS = set()

# ==============================
#  وظائف إرسال الرسائل
# ==============================

def send_message(chat_id: int, text: str, reply_markup=None):
    """يرسل رسالة تلغرام."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)

        r = HTTP_SESSION.post(url, json=payload, timeout=5)
        r.raise_for_status()
        return r.json()

    except Exception as e:
        logger.exception("SendMessage error: %s", e)
        return None


def broadcast_message(text: str):
    """إرسال رسالة لكل الشاتات."""
    sent = []
    for cid in list(KNOWN_CHAT_IDS):
        try:
            send_message(cid, text)
            sent.append(cid)
        except Exception:
            pass
    return sent

# ==============================
#  TRACKING
# ==============================

LAST_WEBHOOK_TICK = None
LAST_REALTIME_TICK = None
LAST_WEEKLY_TICK = None
LAST_WEEKLY_SENT_DATE = None
