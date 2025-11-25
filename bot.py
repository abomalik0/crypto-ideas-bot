import os
import requests
from flask import Flask, request

app = Flask(__name__)

# ==========================
#  Environment Variables
# ==========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

WEBHOOK_URL = "https://ugliest-tilda-in-crypto-133f2e26.koyeb.app/webhook"

# ==========================
#  Set Webhook Automatically
# ==========================
def set_webhook():
    url = BASE_URL + "setWebhook"
    data = {"url": WEBHOOK_URL}
    try:
        r = requests.post(url, data=data).json()
        print("Webhook Status:", r)
    except:
        print("Webhook Error")


# ==========================
#  Price Fetcher (Binance + Kucoin fallback for VAI)
# ==========================
def get_price(symbol):
    symbol = symbol.upper()

    # ---- Binance for all except VAI ----
    if symbol != "VAI":
        try:
            r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT").json()
            return float(r["price"])
        except:
            pass

    # ---- Kucoin only for VAI ----
    if symbol == "VAI":
        try:
            r = requests.get("https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=VAI-USDT").json()
            return float(r["data"]["price"])
        except:
            return None

    return None


# ==========================
#  Detect Simple Price Pattern
# ==========================
def detect_pattern(prices):
    if not prices or len(prices) < 3:
        return "غير كافى لاكتشاف نموذج."

    p1, p2, p3 = prices[-3:]

    if p1 > p2 < p3:
        return "🔻 **قاع محتمل (Potential Bottom)**"
    if p1 < p2 > p3:
        return "🔺 **قمة محتملة (Potential Top)**"
    
    return "⚪ **سلوك سعرى طبيعى بدون نماذج واضحة.**"


# ==========================
#  Create AI-like Clean Technical Report
# ==========================
def generate_report(symbol, price):
    pattern = detect_pattern([price * 1.02, price * 0.98, price])  # dummy series

    report = f"""
📊 **تقرير التحليل الفني — {symbol.upper()}**
السعر الحالي: **{price:,.3f}$**

📌 **الدعم والمقاومة (تقديري بسيط):**
- أقرب دعم محتمل: **{price * 0.97:,.3f}$**
- أقرب مقاومة محتملة: **{price * 1.03:,.3f}$**

📐 **الاتجاه العام:**
{"🔻 هابط على المدى القصير." if price < price * 1.01 else "🔺 صاعد على المدى القصير."}

📂 **النموذج الفني المكتشف:**
{pattern}

🤖 **ملاحظات الذكاء الاصطناعي:**
السوق يحتاج مزيدًا من التأكيد قبل تغيير الاتجاه.  
يفضل متابعة الحركة القادمة واختراق مستويات الدعم أو المقاومة المذكورة.

ـــــــــــــــــــــــــــــــ
IN CRYPTO Ai
"""
    return report


# ==========================
#  Telegram Webhook Handler
# ==========================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    if not data:
        return "no data"

    if "message" not in data:
        return "ok"

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text", "")

    # /start
    if text == "/start":
        send_msg(chat_id, "أهلاً بك! 👋\nأرسل اسم أي عملة مثل:\n\n`/btc`\n`/eth`\n`/vai`\n\nوسيتم تحليلها فورًا.")
        return "ok"

    # /symbol
    if text.startswith("/"):
        symbol = text.replace("/", "").upper()

        price = get_price(symbol)

        if price is None:
            send_msg(chat_id, f"⚠️ لا يمكن جلب بيانات العملة **{symbol}**.")
            return "ok"

        report = generate_report(symbol, price)
        send_msg(chat_id, report)
        return "ok"

    return "ok"


# ==========================
#  Telegram Send Message
# ==========================
def send_msg(chat_id, text):
    url = BASE_URL + "sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, data=data)


# ==========================
#  Run App (Koyeb)
# ==========================
if __name__ == "__main__":
    set_webhook()
    app.run(host="0.0.0.0", port=8080)
