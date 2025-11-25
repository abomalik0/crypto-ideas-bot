import requests
from flask import Flask, request

# ===========================
#   إعدادات عامة
# ===========================
TOKEN = "YOUR_TELEGRAM_TOKEN"   # ← ضع التوكن هنا
WEBHOOK_URL = "YOUR_WEBHOOK_URL/webhook"  # ← ضع رابط السيرفر

BINANCE_API = "https://api.binance.com/api/v3"
KUCOIN_API = "https://api.kucoin.com/api/v1"

# ===========================
#   Flask
# ===========================
app = Flask(__name__)


# ============================================================
#   أدوات مساعدة
# ============================================================

def format_number(x: float) -> str:
    try:
        if x >= 100:
            return f"{x:,.0f}"
        elif x >= 1:
            return f"{x:,.2f}"
        else:
            return f"{x:,.4f}"
    except:
        return str(x)


def build_trend_section(price: float, ma20: float, ma50: float) -> str:
    price_f = format_number(price)
    ma20_f = format_number(ma20)
    ma50_f = format_number(ma50)

    # تحديد الاتجاه
    if price > ma20 and price > ma50:
        trend = "صاعد"
        base = 2
    elif price < ma20 and price < ma50:
        trend = "هابط"
        base = 2
    else:
        trend = "عرضي / انتقالى"
        base = 1

    # قوة الاتجاه
    diff = abs(ma20 - ma50) / ma50 if ma50 != 0 else 0
    if diff > 0.05:
        strength = "قوي 🔥"
    elif diff > 0.02:
        strength = "متوسط ⚖️"
    else:
        strength = "ضعيف 🌫️"

    # شرح
    if trend == "صاعد":
        explain = "السعر أعلى من المتوسطات مما يدعم استمرار الاتجاه الإيجابي."
    elif trend == "هابط":
        explain = "السعر أسفل المتوسطات مما يعكس ضغط بيعي واضح."
    else:
        explain = "السعر بين المتوسطات — حالة تذبذب وعدم وضوح اتجاه."

    return (
        "📊 *الاتجاه العام والمتوسطات*\n"
        f"• السعر الحالي: `{price_f}`\n"
        f"• متوسط 20 يوم: `{ma20_f}`\n"
        f"• متوسط 50 يوم: `{ma50_f}`\n"
        f"• الاتجاه: *{trend}* — قوة {strength}\n"
        f"• قراءة: {explain}\n"
    )


def build_support_resistance(candles):
    closes = [c[4] for c in candles]

    support = min(closes)
    resistance = max(closes)

    return (
        "📌 *مستويات الدعم والمقاومة*\n"
        f"• أقرب دعم: `{format_number(support)}`\n"
        f"• أقرب مقاومة: `{format_number(resistance)}`\n"
    )


def get_binance_klines(symbol):
    url = f"{BINANCE_API}/klines?symbol={symbol}&interval=1d&limit=60"
    r = requests.get(url).json()
    return r


def get_kucoin_price(symbol):
    r = requests.get(f"{KUCOIN_API}/market/orderbook/level1?symbol={symbol}").json()
    return float(r["data"]["price"])


def get_price(symbol):
    # Binance أولاً
    try:
        url = f"{BINANCE_API}/ticker/price?symbol={symbol}"
        r = requests.get(url).json()
        if "price" in r:
            return float(r["price"])
    except:
        pass

    # KuCoin فقط VAIUSDT
    if symbol == "VAIUSDT":
        return get_kucoin_price("VAI-USDT")

    return None


def calc_ma(candles, period):
    closes = [float(c[4]) for c in candles]
    if len(closes) < period:
        return sum(closes) / len(closes)
    return sum(closes[-period:]) / period


# ============================================================
#   تحليل العملة
# ============================================================

def analyze(symbol: str) -> str:
    symbol = symbol.upper()

    price = get_price(symbol)
    if price is None:
        return "⚠️ العملة غير موجودة على Binance أو غير مدعومة."

    # شموع
    if symbol == "VAIUSDT":
        return (
            f"💠 تحليل عملة *{symbol}*\n\n"
            f"⚠️ البيانات المتقدمة (متوسطات – نماذج – دعم/مقاومة) غير متاحة لعملة VAI.\n"
            f"السعر الحالي: `{format_number(price)}`"
        )

    candles = get_binance_klines(symbol)

    ma20 = calc_ma(candles, 20)
    ma50 = calc_ma(candles, 50)

    trend_text = build_trend_section(price, ma20, ma50)
    sr_text = build_support_resistance(candles)

    final = (
        f"💠 *تحليل العملة:* `{symbol}`\n\n"
        f"{trend_text}\n"
        f"{sr_text}\n"
        "🤖 *ملاحظة*: هذا تحليل تقني مبسط مناسب للاستخدام السريع على الخطة المجانية."
    )

    return final


# ============================================================
#   Telegram Webhook
# ============================================================

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        if text.startswith("/coin"):
            parts = text.split()
            if len(parts) == 2:
                symbol = parts[1].upper()
                result = analyze(symbol)
            else:
                result = "اكتب الأمر هكذا:\n/coin BTCUSDT"

            send_message(chat_id, result)

    return "ok", 200


# ============================================================
#   إرسال رسالة
# ============================================================

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)


# ============================================================
#   تشغيل
# ============================================================

if __name__ == "__main__":
    # تعيين الويبهوك تلقائيًا
    wh = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={WEBHOOK_URL}"
    requests.get(wh)

    print("Bot is running...")
    app.run(host="0.0.0.0", port=8080)
