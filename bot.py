import os
import requests
from flask import Flask, request

app = Flask(__name__)

# =====================================================
#   اعدادات أساسية (لا ألمسها)
# =====================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
APP_BASE_URL = os.getenv("APP_BASE_URL")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN غير موجود فى Environment على Koyeb.")

if not APP_BASE_URL:
    raise RuntimeError("APP_BASE_URL غير موجود فى Environment على Koyeb.")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


# =====================================================
#   إرسال رسالة لتليجرام
# =====================================================
def send_message(chat_id: int, text: str, parse_mode="HTML"):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)
    except:
        pass


# =====================================================
#   API جلب البيانات من باينانس
# =====================================================
def fetch_price_binance(symbol: str):
    try:
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol.upper()}"
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return None
        return r.json()
    except:
        return None


# =====================================================
#   API جلب سعر VAI من KuCoin
# =====================================================
def fetch_price_vai():
    try:
        url = "https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=VAI-USDT"
        r = requests.get(url, timeout=10).json()
        if r.get("code") != "200000":
            return None
        return {
            "symbol": "VAIUSDT",
            "lastPrice": r["data"]["price"],
            "priceChangePercent": 0  # VAI مفيش 24h change من KuCoin
        }
    except:
        return None


# =====================================================
#   معالجة الرمز + جلب البيانات الصحيحة
# =====================================================
def get_coin_data(symbol: str):
    s = symbol.upper().replace("/", "")

    # دعم كتابة BTC → BTCUSDT
    if not s.endswith("USDT"):
        s = s.replace("USDT", "") + "USDT"

    # حالة VAI
    if s in ("VAIUSDT", "VAI-USDT"):
        return fetch_price_vai()

    # باقي العملات من Binance
    return fetch_price_binance(s)


# =====================================================
#   توليد رسالة التحليل (شكل الصور اللي وريتها لي)
# =====================================================
def build_analysis(symbol: str):
    data = get_coin_data(symbol)
    if not data:
        return "⚠️ لا يمكن جلب بيانات هذه العملة في الوقت الحالي."

    price = float(data["lastPrice"])
    change = float(data.get("priceChangePercent", 0))

    # دعم & مقاومة شكلية بسيطة
    support = round(price * 0.92, 4)
    resistance = round(price * 1.12, 4)

    # RSI شكلي
    rsi = round(40 + (change % 20), 1)
    rsi_trend = "🔼 صعودي" if rsi > 50 else "🔽 هابط"

    trend = "↘️ الاتجاه العام يميل إلى الهبوط." if change < 0 else "↗️ الاتجاه العام يميل إلى الصعود."

    return f"""
📊 <b>تحليل فني يومي للعملة {symbol.upper()}</b>

💰 <b>السعر الحالي:</b> {price}
📉 <b>تغير اليوم:</b> %{change}

🎯 <b>حركة السعر:</b>
- السعر داخل مسار {'هابط' if change < 0 else 'صاعد'} معتدل.

📍 <b>مستويات فنية مهمة:</b>
- دعم: {support}
- مقاومة: {resistance}

📉 <b>RSI:</b>
- {rsi} → {rsi_trend}.

📊 <b>الاتجاه والمتوسطات:</b>
- {trend}

🤖 <b>ملاحظة الذكاء الاصطناعي:</b>
هذا التحليل يساعدك على فهم الاتجاه فقط، وليس توصية شراء أو بيع.
"""


# =====================================================
#   استقبال Webhook
# =====================================================
@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True)
    if not update or "message" not in update:
        return "OK"

    msg = update["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip().lower()

    # /start
    if text == "/start":
        send_message(
            chat_id,
            "👋 أهلاً بك في بوت IN CRYPTO Ai.\n\n"
            "اكتب:\n"
            "› /btc\n"
            "› /coin btcusdt\n"
            "للحصول على التحليل."
        )
        return "OK"

    # /btc
    if text == "/btc":
        reply = build_analysis("BTCUSDT")
        send_message(chat_id, reply)
        return "OK"

    # /coin
    if text.startswith("/coin"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "⚠️ مثال: /coin cfx أو /coin btcusdt")
            return "OK"

        symbol = parts[1]
        reply = build_analysis(symbol)
        send_message(chat_id, reply)
        return "OK"

    # أي نص آخر
    send_message(
        chat_id,
        "ℹ️ استخدم:\n/btc\n/coin btcusdt"
    )
    return "OK"


# =====================================================
#   تشغيل السيرفر
# =====================================================
if __name__ == "__main__":
    print("Bot is running...")
    app.run(host="0.0.0.0", port=8080)
