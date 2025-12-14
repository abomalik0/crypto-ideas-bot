# ============================================================
#  BOT FINAL STABLE — NO INLINE — SINGLE WEBHOOK — KOYEB READY
#  WITH FULL DIAGNOSTICS + FAST ACK
# ============================================================

from flask import Flask, request, jsonify
import requests
import os
import logging

# ============================================================
#  BASIC CONFIG
# ============================================================

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
APP_BASE_URL = (os.getenv("APP_BASE_URL") or "").strip()  # لازم يكون https://xxxxx.koyeb.app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

app = Flask(__name__)

if not BOT_TOKEN:
    logging.warning("BOT_TOKEN is missing!")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

HTTP = requests.Session()

# ============================================================
#  HELPERS
# ============================================================

def normalize_base_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    # لو المستخدم حط الدومين بس
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    # شيل أي /
    url = url.rstrip("/")
    return url

def tg(method: str, params=None, json=None, timeout=12):
    try:
        r = HTTP.post(f"{TELEGRAM_API}/{method}", params=params, json=json, timeout=timeout)
        return r
    except Exception as e:
        logging.exception("Telegram call failed: %s", e)
        return None

def send_message(chat_id, text: str):
    if not chat_id:
        return
    if text is None:
        text = ""
    text = str(text)

    # تقسيم آمن للرسائل الطويلة
    max_len = 3500
    chunks = [text[i:i+max_len] for i in range(0, len(text), max_len)] or [""]

    for ch in chunks:
        tg("sendMessage", json={
            "chat_id": chat_id,
            "text": ch,
            "disable_web_page_preview": True
        }, timeout=10)

# ============================================================
#  ROUTES
# ============================================================

@app.route("/", methods=["GET"])
def home():
    # افتح الدومين في المتصفح وشوف الرسالة دي
    return "OK - Bot server is running ✅", 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

# ============================================================
#  WEBHOOK ROUTE — SINGLE ONLY
# ============================================================

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}

    # log update (مختصر)
    try:
        upd_id = data.get("update_id")
        logging.info("Webhook hit ✅ update_id=%s keys=%s", upd_id, list(data.keys()))
    except Exception:
        logging.info("Webhook hit ✅ (could not parse keys)")

    # Telegram ممكن يبعت callback_query / message / edited_message...
    message = data.get("message") or data.get("edited_message")
    callback = data.get("callback_query")

    # رد سريع أولًا (FAST ACK) — ثم اشتغل
    # (Flask بيرجع في الآخر، بس هنقلل الحمل بأي شكل)
    if callback:
        # لو وصل inline قديم او callback — هنرد برسالة بسيطة بدل ما يهنج
        chat_id = (callback.get("message") or {}).get("chat", {}).get("id")
        send_message(chat_id, "✅ تم استقبال الضغط. اكتب /start أو اسم العملة.")
        return "ok", 200

    if not message:
        return "ok", 200

    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()

    logging.info("Incoming message chat_id=%s text=%r", chat_id, text)

    if text == "/start":
        send_message(chat_id, "✅ البوت شغال وبيرد طبيعي.\nاكتب اسم العملة مثل: BTCUSDT")
        return "ok", 200

    if not text:
        send_message(chat_id, "اكتب أمر أو اسم عملة.")
        return "ok", 200

    # رد سريع بدون تهنيج
    send_message(chat_id, f"📌 تم استلام: {text}\n⏳ جاري تجهيز التحليل...")

    return "ok", 200

# ============================================================
#  WEBHOOK SETUP (DELETE THEN SET)
# ============================================================

def setup_webhook():
    base = normalize_base_url(APP_BASE_URL)

    if not BOT_TOKEN:
        logging.error("BOT_TOKEN missing -> cannot set webhook")
        return

    if not base:
        logging.warning("APP_BASE_URL missing -> skipping setWebhook")
        return

    webhook_url = f"{base}/webhook"

    # 1) deleteWebhook + drop pending
    try:
        r = tg("deleteWebhook", json={"drop_pending_updates": True}, timeout=15)
        if r is not None:
            logging.info("deleteWebhook: %s - %s", r.status_code, r.text)
    except Exception as e:
        logging.exception("deleteWebhook failed: %s", e)

    # 2) setWebhook
    try:
        r = tg("setWebhook", json={
            "url": webhook_url,
            "allowed_updates": ["message", "edited_message", "callback_query"]
        }, timeout=15)
        if r is not None:
            logging.info("setWebhook: %s - %s", r.status_code, r.text)
    except Exception as e:
        logging.exception("setWebhook failed: %s", e)

    # 3) getWebhookInfo (للتأكد)
    try:
        r = tg("getWebhookInfo", timeout=15)
        if r is not None:
            logging.info("getWebhookInfo: %s - %s", r.status_code, r.text)
    except Exception as e:
        logging.exception("getWebhookInfo failed: %s", e)

# ============================================================
#  MAIN RUNNER
# ============================================================

if __name__ == "__main__":
    setup_webhook()
    app.run(host="0.0.0.0", port=8080)
