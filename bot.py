# ============================================================
#  BOT FINAL STABLE — NO INLINE — SINGLE WEBHOOK — KOYEB READY
# ============================================================

from flask import Flask, request
import requests
import os
import logging
import time

# ============================================================
#  BASIC CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
APP_BASE_URL = os.getenv("APP_BASE_URL", "").strip()

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

app = Flask(__name__)

# ============================================================
#  SAFE SEND MESSAGE (ANTI-HANG + SPLIT)
# ============================================================

def send_message(chat_id, text):
    if not text:
        return
    url = f"{TELEGRAM_API}/sendMessage"
    max_len = 3500
    for i in range(0, len(text), max_len):
        try:
            requests.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": text[i:i+max_len],
                    "disable_web_page_preview": True
                },
                timeout=8
            )
        except Exception as e:
            logging.exception("Send message failed: %s", e)

# ============================================================
#  WEBHOOK ROUTE — SINGLE ONLY
# ============================================================

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}

    message = data.get("message")
    if not message:
        return "ok", 200

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = message.get("text", "")

    if not chat_id:
        return "ok", 200

    # ===============================
    #  BASIC COMMANDS
    # ===============================

    if text == "/start":
        send_message(
            chat_id,
            "✅ البوت شغال بثبات\n"
            "🚀 بدون Inline\n"
            "⚡ بدون تهنيج\n\n"
            "اكتب اسم العملة أو الأمر المطلوب."
        )
        return "ok", 200

    # ===============================
    #  PLACEHOLDER FOR ANALYSIS ENGINE
    # ===============================

    send_message(
        chat_id,
        f"📊 تم استلام طلبك:\n{text}\n\n"
        "⏳ التحليل قيد المعالجة..."
    )

    return "ok", 200

# ============================================================
#  SET WEBHOOK (ON STARTUP)
# ============================================================

def setup_webhook():
    if not BOT_TOKEN or not APP_BASE_URL:
        logging.warning("Webhook not set (missing BOT_TOKEN or APP_BASE_URL)")
        return

    webhook_url = f"{APP_BASE_URL}/webhook"
    try:
        r = requests.get(
            f"{TELEGRAM_API}/setWebhook",
            params={"url": webhook_url},
            timeout=10
        )
        logging.info("Webhook response: %s - %s", r.status_code, r.text)
    except Exception as e:
        logging.exception("Webhook setup failed: %s", e)

# ============================================================
#  MAIN RUNNER
# ============================================================

if __name__ == "__main__":
    setup_webhook()
    app.run(host="0.0.0.0", port=8080)
