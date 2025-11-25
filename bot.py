import requests
from flask import Flask, request

TOKEN = "8207052650:AAEJ7qyoWqDYyMyllsNuyZHzLynlTM4x9os"
WEBHOOK_URL = "https://ugliest-tilda-in-crypto-133f2e26.koyeb.app/webhook"

app = Flask(__name__)

# ===========================
# دوال التحليل
# ===========================

def get_price(symbol):
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}"
        r = requests.get(url).json()
        return float(r["price"])
    except:
        return None


def get_kline(symbol, interval="1h"):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol.upper()}&interval={interval}&limit=50"
        r = requests.get(url).json()
        return r
    except:
        return None


def get_rsi(symbol, interval="1h"):
    data = get_kline(symbol, interval)
    if not data:
        return None

    closes = [float(c[4]) for c in data]
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]

    gains = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]

    if len(gains) == 0 or len(losses) == 0:
        return 50

    avg_gain = sum(gains) / len(gains)
    avg_loss = sum(losses) / len(losses)

    rs = avg_gain / avg_loss if avg_loss != 0 else 1
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)


def classify_trend(rsi):
    if rsi > 60:
        return "صاعد", "قوية"
    elif rsi < 40:
        return "هابط", "ضعيفة"
    else:
        return "جانبي", "متوسطة"


def generate_price_behavior(trend, strength, zone, behavior):
    return f"""
🔍 **حركة السعر**
• **الاتجاه:** {trend}
• **قوة الاتجاه:** {strength}
• **موقع السعر:** {zone}
• **سلوك الحركة:** {behavior}
"""


# ===========================
# إنشاء التحليل النهائي
# ===========================

def build_analysis(symbol):
    price = get_price(symbol)
    rsi = get_rsi(symbol)

    if price is None:
        return "⚠️ العملة غير موجودة أو غير مدعومة."

    trend, strength = classify_trend(rsi)

    zone = "قريب من دعم" if rsi < 45 else "قريب من مقاومة"
    behavior = "حركة مستقرة" if 45 < rsi < 55 else "اندفاع واضح في الحركة"

    price_behavior = generate_price_behavior(trend, strength, zone, behavior)

    return f"""
📌 **تحليل {symbol.upper()}**

💰 **السعر الحالي:** {price}
📊 **مؤشر RSI:** {rsi}

{price_behavior}

📌 **الملخص**
• الاتجاه العام: {trend}
• قوة الاتجاه: {strength}
"""


# ===========================
# WEBHOOK
# ===========================

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        if text.startswith("/coin"):
            parts = text.split()
            if len(parts) < 2:
                send_message(chat_id, "استخدم الأمر بالشكل:\n/coin BTCUSDT")
                return "OK", 200

            symbol = parts[1].upper()
            analysis = build_analysis(symbol)
            send_message(chat_id, analysis)

        elif text == "/start":
            send_message(chat_id,
                "💎 أهلاً بك!\n"
                "لتحليل أي عملة أرسل:\n"
                "/coin BTCUSDT"
            )

    return "OK", 200


def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})


# ===========================
# Run Flask (Koyeb)
# ===========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
