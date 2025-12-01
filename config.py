import os
import logging
import requests

# ==============================
#   إعدادات التوكن والبوت
# ==============================

BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT-YOUR-TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

API_ID = os.getenv("API_ID", "")
API_HASH = os.getenv("API_HASH", "")

BOT_DEBUG = True  # لو false مش هيعرض Debug Messages

# ==============================
#   جلسة HTTP سريعة
# ==============================

HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({"User-Agent": "INCRYPTO-AI-BOT/1.0"})

# ==============================
#   نظام تسجيل (LOGGER)
# ==============================

logger = logging.getLogger("INCRYPTO_AI")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(handler)

# ==============================
#   كاش بيانات السوق
# ==============================

MARKET_TTL_SECONDS = 20   # مدة حياة الكاش — ممتاز للسرعة
MARKET_METRICS_CACHE = {
    "symbol": None,
    "ts": 0,
    "price": None,
    "high": None,
    "low": None,
    "volume": None,
    "change_pct": None,
}

# ==============================
#   حالة الـ API
# ==============================

API_STATUS = {
    "binance_ok": True,
    "kucoin_ok": True,
    "last_error": None,
    "last_api_check": None,
}

# ==============================
#   دوال إرسال الرسائل
# ==============================

def send_message(chat_id, text, parse_mode="HTML"):
    """يرسل رسالة مباشرة بدون كيبورد."""
    try:
        r = HTTP_SESSION.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
            },
            timeout=5,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error("Send message error: %s", e)
        return False


def send_message_with_keyboard(chat_id, text, keyboard=None, parse_mode="HTML"):
    """
    يرسل رسالة مع كيبورد Inline.
    لو keyboard=None → يرسل بدون كيبورد.
    """
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }

    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}

    try:
        r = HTTP_SESSION.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=5,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error("Send keyboard message error: %s", e)
        return False


# ==============================
#   دالة إرسال Alert جماعى (لو لسه هنعملها)
# ==============================

def broadcast_alert(chat_ids: list, text: str):
    sent = 0
    for cid in chat_ids:
        if send_message(cid, text):
            sent += 1
    return sent
