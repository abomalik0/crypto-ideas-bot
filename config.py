import os
import logging
import requests

# ==============================
#   Logger
# ==============================
logger = logging.getLogger("crypto_bot")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(handler)

# ==============================
#   ENVIRONMENT
# ==============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

if not BOT_TOKEN:
    raise RuntimeError("البيئة لا تحتوى على BOT_TOKEN")

if not ADMIN_CHAT_ID:
    raise RuntimeError("البيئة لا تحتوى على ADMIN_CHAT_ID")

BOT_DEBUG = True  # لو مش عايزه اطفيه حط False

# ==============================
#   HTTP Session
# ==============================
HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({"User-Agent": "CryptoAI Bot"})

# ==============================
#   API STATUS TRACKING
# ==============================
API_STATUS = {
    "binance_ok": True,
    "kucoin_ok": True,
    "last_error": None,
    "last_api_check": None,
}

# ==============================
#   CACHE
# ==============================
MARKET_METRICS_CACHE = {}
MARKET_TTL_SECONDS = 8  # مدة الكاش 8 ثوانى

# ==============================
#   Telegram Helpers
# ==============================

def send_message(chat_id, text, parse_mode="HTML", reply_markup=None):
    """إرسال رسالة عادية"""
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        r = HTTP_SESSION.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload, timeout=5
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error("send_message error: %s", e)
        return None


def send_message_with_keyboard(chat_id, text, keyboard, parse_mode="HTML"):
    """إرسال رسالة مع Inline Keyboard"""
    try:
        r = HTTP_SESSION.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": {"inline_keyboard": keyboard},
            },
            timeout=5,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error("keyboard send error: %s", e)
        return None


def answer_callback_query(callback_query_id, text="", show_alert=False):
    """الرد على ضغط زر Inline"""
    try:
        r = HTTP_SESSION.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
            json={
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": show_alert,
            },
            timeout=5,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error("callback_query error: %s", e)
        return False


def edit_message(chat_id, message_id, new_text, keyboard=None):
    """تعديل رسالة سابقة"""
    try:
        data = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": new_text,
            "parse_mode": "HTML",
        }
        if keyboard:
            data["reply_markup"] = {"inline_keyboard": keyboard}

        r = HTTP_SESSION.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText",
            json=data,
            timeout=5,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error("edit_message error: %s", e)
        return False


def delete_message(chat_id, message_id):
    """حذف رسالة"""
    try:
        r = HTTP_SESSION.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage",
            json={"chat_id": chat_id, "message_id": message_id},
            timeout=5,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error("delete_message error: %s", e)
        return False


# ==============================
#   Broadcast Helper
# ==============================

def broadcast_message(chat_ids: list[int], text: str):
    """إرسال رسالة لكل المستخدمين"""
    for cid in chat_ids:
        send_message(cid, text)
