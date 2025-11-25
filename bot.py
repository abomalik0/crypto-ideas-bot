import os
import requests
from flask import Flask, request, jsonify

TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "cryptoAI")

app = Flask(__name__)

# =============================
# 📌 جلب بيانات العملة من Binance
# =============================
def get_price_and_data(symbol):
    try:
        symbol = symbol.upper()
        price_url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        depth_url = f"https://api.binance.com/api/v3/depth?symbol={symbol}&limit=5"
        rsi_url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=15"

        # السعر
        price_r = requests.get(price_url).json()
        if "price" not in price_r:
            return None

        # دفتر أوامر بسيط
        depth = requests.get(depth_url).json()

        # RSI
        rsi_data = requests.get(rsi_url).json()
        closes = [float(c[4]) for c in rsi_data]
        rsi_value = calculate_rsi(closes)

        # دعم/مقاومة
        levels = detect_support_resistance(closes)

        return {
            "price": float(price_r["price"]),
            "rsi": rsi_value,
            "levels": levels
        }

    except Exception as e:
        print("ERROR:", e)
        return None

# =============================
# 📌 RSI
# =============================
def calculate_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None

    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[-i] - closes[-i - 1]
        if diff >= 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))

    avg_gain = sum(gains) / period if gains else 0.0001
    avg_loss = sum(losses) / period if losses else 0.0001

    rs = avg_gain / avg_loss
    rsi = round(100 - (100 / (1 + rs)), 2)
    return rsi

# =============================
# 📌 كشف دعم ومقاومة بسيطة
# =============================
def detect_support_resistance(closes):
    if len(closes) < 10:
        return []

    levels = []
    for i in range(2, len(closes) - 2):
        if closes[i] < closes[i-1] and closes[i] < closes[i+1]:
            levels.append(("Support", closes[i]))
        if closes[i] > closes[i-1] and closes[i] > closes[i+1]:
            levels.append(("Resistance", closes[i]))

    return levels[-3:]  # آخر 3 مستويات فقط

# =============================
# 📌 تنسيق الرسالة الاحترافية لـ /coin
# =============================
def format_coin_message(symbol, data):
    price = data["price"]
    rsi = data["rsi"]
    levels = data["levels"]

    msg = f"""
📊 **تحليل سريع لعملة {symbol.upper()}**

💰 **السعر الحالي:** `${price:,.4f}`

📈 **اتجاه عام مختصر**
- RSI: **{rsi}**
- الحالة: {"🔺 ميل صعودي معتدل" if rsi > 55 else "🔻 ضغط بيعي" if rsi < 45 else "⚪ حيادي"}

🧱 **مستويات فنية مهمة**
"""
    if not levels:
        msg += "- لا توجد مستويات واضحة حاليًا.\n"
    else:
        for lvl_type, lvl_price in levels:
            emoji = "🟢" if lvl_type == "Support" else "🔴"
            msg += f"- {emoji} {lvl_type}: `${lvl_price:,.3f}`\n"

    msg += """

🧠 **نظرة مختصرة**
العملة في نطاق متابعة حاليًا، وتحتاج مراقبة إضافية قبل اتخاذ قرار تداول.

🚀 IN CRYPTO – AI
"""
    return msg

# =============================
# 📌 إرسال رسالة لتليجرام
# =============================
def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

# =============================
# 📌 Webhook الأساسي
# =============================
@app.route("/webhook", methods=["POST"])
def webhook():
    if WEBHOOK_SECRET not in request.args.get("token", ""):
        return jsonify({"status": "forbidden"}), 403

    data = request.get_json()

    if "message" not in data:
        return jsonify({"ok": True})

    chat_id = data["message"]["chat"]["id"]
    text = data["message"].get("text", "")

    # =============================
    # 📌 أمر /coin
    # =============================
    if text.startswith("/coin"):
        try:
            parts = text.split()
            if len(parts) < 2:
                send_message(chat_id, "❗ يرجى كتابة العملة هكذا:\n/coin btcusdt")
                return jsonify({"ok": True})

            symbol = parts[1].upper()

            coin_data = get_price_and_data(symbol)
            if not coin_data:
                send_message(chat_id, "⚠️ لم يتم العثور على بيانات لهذه العملة.")
                return jsonify({"ok": True})

            msg = format_coin_message(symbol, coin_data)
            send_message(chat_id, msg)

        except Exception as e:
            send_message(chat_id, f"خطأ غير متوقع: {e}")

    return jsonify({"ok": True})


# =============================
# 📌 Run Flask locally
# =============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
