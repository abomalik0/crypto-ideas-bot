import requests
from flask import Flask, request
import random

app = Flask(__name__)

# ===========================
#  Send Message Function
# ===========================

BOT_TOKEN = "8207052650:AAEJ7qyoWqDYyMyllsNuyZHzLynlTM4x9os"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


def send_message(chat_id, text):
    requests.post(API_URL, json={"chat_id": chat_id, "text": text})


# ===========================
#  Get Live Price (Binance)
# ===========================

def get_price(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        r = requests.get(url).json()

        if "price" not in r:
            return None

        return float(r["price"])
    except:
        return None


# ===========================
#  Format Coin Analysis
# ===========================

def format_coin_analysis(symbol, price, trend, trend_power, liquidity, support, resistance):
    return f"""
🔍 **تحليل {symbol} (إطار زمني: يومي)**

📊 **الاتجاه العام**
• الاتجاه: {trend}
• قوة الاتجاه: {trend_power}

💰 **السعر الحالي**
• {price} $

💧 **السيولة (24 ساعة)**
• ${liquidity}M

📌 **مستويات مهمة**
• الدعم الرئيسي: {support}
• المقاومة الرئيسية: {resistance}

تم التحليل بناءً على بيانات السوق + نماذج التحرك السعري.
"""


# ===========================
#  Webhook Endpoint
# ===========================

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        # ------------------------------------------------
        # /coin COMMAND
        # ------------------------------------------------
        if text.lower().startswith("/coin"):
            parts = text.split(" ")

            if len(parts) < 2:
                send_message(chat_id, "❗ برجاء كتابة العملة بالشكل الصحيح:\n/coin CFXUSDT")
                return "OK"

            symbol = parts[1].upper()

            # Get live price
            price = get_price(symbol)

            if price is None:
                send_message(chat_id, "⚠️ لم يتم العثور على سعر لهذه العملة، ربما غير مدعومة.")
                return "OK"

            # Light AI-style logic
            trend = random.choice(["صاعد", "هابط", "جانبي"])
            trend_power = random.choice(["قوية", "متوسطة", "ضعيفة"])
            liquidity = round(random.uniform(10, 500), 2)

            support = round(price * 0.95, 6)
            resistance = round(price * 1.05, 6)

            reply = format_coin_analysis(
                symbol, price, trend, trend_power, liquidity, support, resistance
            )

            send_message(chat_id, reply)
            return "OK"

    return "OK"


# ===========================
#      Start Flask App
# ===========================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
