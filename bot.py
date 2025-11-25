from flask import Flask, request
import requests
import json
import time

TOKEN = "8207052650:AAEJ7qyoWqDYyMyllsNuyZHzLynlTM4x9os"
WEBHOOK_URL = "https://ugliest-tilda-in-crypto-133f2e26.koyeb.app/webhook"

app = Flask(__name__)


# ==============================
# 1) جلب السعر من Binance
# ==============================
def get_price(symbol):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}"
    r = requests.get(url).json()
    return float(r["price"])


# ==============================
# 2) جلب الشموع اليومية
# ==============================
def get_klines(symbol, interval="1d", limit=200):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    return requests.get(url).json()


# ==============================
# 3) حساب RSI
# ==============================
def calculate_rsi(prices, period=14):
    if len(prices) < period:
        return 50
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = prices[-i] - prices[-i - 1]
        if diff >= 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))
    avg_gain = sum(gains) / period if gains else 0.01
    avg_loss = sum(losses) / period if losses else 0.01
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ==============================
# 4) نماذج بسيطة
# ==============================
def detect_patterns(closes):
    if len(closes) < 5:
        return "لا يوجد نموذج."
    a, b, c, d, e = closes[-5:]
    if a > b < c > d < e:
        return "نموذج محتمل لتغير الاتجاه."
    return "لا يوجد نموذج واضح حالياً."


# ==============================
# 5) تحليل العملة بالكامل
# ==============================
def analyze_coin(symbol):
    try:
        symbol = symbol.upper()

        price = get_price(symbol)
        data = get_klines(symbol)
        closes = [float(c[4]) for c in data]

        # الاتجاه العام
        trend = "اتجاه صاعد" if closes[-1] > closes[-50] else "اتجاه هابط"

        # سلوك السعر
        if closes[-1] > closes[-2]:
            pa = "تحسن في الحركة اليومية."
        else:
            pa = "ضغط بيعي واضح."

        # دعم / مقاومة
        support = min(closes[-30:])
        resistance = max(closes[-30:])

        # متوسطات
        ma50 = sum(closes[-50:]) / 50
        ma200 = sum(closes) / len(closes)
        ma_state = "إيجابي" if ma50 > ma200 else "سلبي"

        # RSI
        rsi = calculate_rsi(closes)
        if rsi > 70:
            rsi_state = "تشبّع شرائي"
        elif rsi < 30:
            rsi_state = "تشبّع بيعي"
        else:
            rsi_state = "منطقة حيادية"

        # نماذج
        pattern = detect_patterns(closes)

        # الرسالة النهائية
        msg = f"""
📌 **تحليل فني لعملة {symbol}**

💰 **السعر الحالي:** {price}$

📉 **الاتجاه العام:** {trend}
🧭 **سلوك السعر:** {pa}

🎯 **الدعم والمقاومة:**
- الدعم: {support:.2f}
- المقاومة: {resistance:.2f}

📊 **المتوسطات المتحركة:**
- MA50: {ma50:.2f}
- MA200: {ma200:.2f}
- الحالة: {ma_state}

📈 **RSI:** {rsi:.2f} ({rsi_state})

🔷 **النماذج الفنية:**  
{pattern}

🤖 **IN CRYPTO AI**
"""
        return msg

    except Exception as e:
        return f"❌ خطأ أثناء التحليل: {e}"


# ==============================
# 6) الـ Webhook
# ==============================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        if text.startswith("/coin"):
            parts = text.split()
            if len(parts) < 2:
                return send_message(chat_id, "❗ اكتب الأمر هكذا:\n/coin btcusdt")
            symbol = parts[1]
            reply = analyze_coin(symbol)
            send_message(chat_id, reply)

        elif text == "/start":
            send_message(chat_id, "اهلا بك 😊 ارسل /coin ثم رمز العملة")

    return "OK", 200


# ==============================
# 7) إرسال رسالة لتليجرام
# ==============================
def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)


# ==============================
# 8) تشغيل السيرفر
# ==============================
if __name__ == "__main__":
    print("Bot is running...")
    app.run(host="0.0.0.0", port=8080)
