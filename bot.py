import os
import logging
import math
from flask import Flask, request
import requests

# ==========================
# إعداد المتغيرات من Environment
# ==========================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
APP_BASE_URL = os.environ.get("APP_BASE_URL")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

BINANCE_API = "https://api.binance.com"
KUCOIN_API = "https://api.kucoin.com"

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ==========================
# تنسيق السعر
# ==========================

def fmt_price(p: float) -> str:
    if p is None or math.isnan(p):
        return "غير متاح"
    try:
        if p >= 1000:
            s = f"{p:,.0f}"
            return s.replace(",", ".")
        elif p >= 1:
            return f"{p:.2f}".rstrip("0").rstrip(".")
        else:
            return f"{p:.6f}".rstrip("0").rstrip(".")
    except:
        return str(p)

# ==========================
# إرسال رسالة
# ==========================

def send_message(chat_id: int, text: str):
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Error sending message: {e}")

# ==========================
# Binance Klines
# ==========================

def get_binance_klines(symbol: str, limit: int = 120):
    url = f"{BINANCE_API}/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": "1d",
        "limit": limit,
    }
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        raise ValueError("Binance error")
    data = r.json()

    candles = []
    for c in data:
        candles.append({
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
        })
    return candles

# ==========================
# KuCoin price (VAI)
# ==========================

def get_kucoin_last_price():
    url = f"{KUCOIN_API}/api/v1/market/orderbook/level1"
    params = {"symbol": "VAI-USDT"}
    r = requests.get(url, params=params, timeout=10)
    j = r.json()
    return float(j["data"]["price"])

# ==========================
# أدوات فنية (EMA + RSI)
# ==========================

def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema_val = sum(values[:period]) / period
    for price in values[period:]:
        ema_val = price * k + ema_val * (1 - k)
    return ema_val

def rsi(values, period=14):
    if len(values) <= period:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = values[i] - values[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(-diff)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ==========================
# تحليل هيكل السعر
# ==========================

def detect_structure(closes):
    if len(closes) < 30:
        return "لا توجد بيانات كافية لتحديد شكل الحركة."
    recent = closes[-30:]
    start, end = recent[0], recent[-1]

    change_pct = (end - start) / start * 100
    high, low = max(recent), min(recent)
    rng = (high - low) / low * 100

    if abs(change_pct) < 3 and rng < 8:
        return "السعر يتحرك في نطاق عرضي ضيق."
    if change_pct > 3:
        return "السعر داخل مسار صاعد معتدل."
    if change_pct < -3:
        return "السعر داخل مسار هابط معتدل."
    if rng >= 15 and change_pct > 0:
        return "قناة سعرية صاعدة واسعة نسبيًا."
    if rng >= 15 and change_pct < 0:
        return "قناة سعرية هابطة واسعة نسبيًا."
    return "حركة متذبذبة بدون نموذج واضح."

# ==========================
# بناء النص النهائي — النسخة الأصلية
# ==========================

def build_analysis(symbol, candles=None, last_price=None, is_vai=False):
    # عملة VAI من KuCoin (تحليل مبسط)
    if is_vai:
        price = fmt_price(last_price)
        return (
            f"📊 *تحليل مبسط لعملة* `{symbol}`\n\n"
            f"💰 *السعر الحالي:* `{price}`\n\n"
            "🔎 البيانات التاريخية محدودة، لذلك التحليل مبسّط.\n"
            "🤖 يُنصح بحجم مخاطرة أقل بسبب تقلبات العملة."
        )

    # بيانات غير كافية
    if not candles or len(candles) < 20:
        price = fmt_price(last_price)
        return (
            f"📊 *تحليل العملة* `{symbol}`\n\n"
            f"💰 *السعر الحالي:* `{price}`\n\n"
            "لا توجد بيانات كافية لبناء تحليل يومي موثوق."
        )

    closes = [c["close"] for c in candles]
    last_close = closes[-1]
    prev_close = closes[-2]
    change_pct = (last_close - prev_close) / prev_close * 100

    recent = candles[-30:]
    support = min(c["low"] for c in recent)
    resistance = max(c["high"] for c in recent)

    ema_fast = ema(closes, 9)
    ema_slow = ema(closes, 21)
    rsi_value = rsi(closes)

    structure = detect_structure(closes)

    # الاتجاه
    if ema_fast and ema_slow:
        if ema_fast > ema_slow and last_close > ema_fast:
            trend = "الاتجاه العام يميل إلى الصعود."
        elif ema_fast < ema_slow and last_close < ema_slow:
            trend = "الاتجاه العام يميل إلى الهبوط."
        else:
            trend = "الاتجاه العام حيادي."
    else:
        trend = "الاتجاه غير واضح بسبب نقص البيانات."

    # RSI
    if rsi_value is None:
        rsi_text = "لا توجد بيانات RSI كافية."
    elif rsi_value > 70:
        rsi_text = f"RSI `{rsi_value:.1f}` → تشبّع شرائي."
    elif rsi_value < 30:
        rsi_text = f"RSI `{rsi_value:.1f}` → تشبّع بيعي."
    else:
        rsi_text = f"RSI `{rsi_value:.1f}` → حيادي."

    # تنسيق أرقام
    price_txt = fmt_price(last_close)
    support_txt = fmt_price(support)
    resistance_txt = fmt_price(resistance)

    # ------------------------------
    # الرسالة الأصلية كما هي 100%
    # ------------------------------
    return (
        f"📊 *تحليل فني يومي للعملة* `{symbol}`\n\n"
        f"💰 *السعر الحالي:* `{price_txt}`\n"
        f"📈 *تغيّر اليوم:* `{change_pct:.2f}%`\n\n"
        f"🧭 *حركة السعر العامة:*\n"
        f"- {structure}\n\n"
        f"📍 *مستويات فنية مهمة:*\n"
        f"- دعم: `{support_txt}`\n"
        f"- مقاومة: `{resistance_txt}`\n\n"
        f"📊 *صورة الاتجاه والمتوسطات:*\n"
        f"- {trend}\n\n"
        f"📉 *RSI:*\n"
        f"- {rsi_text}\n\n"
        "🤖 *ملاحظة الذكاء الاصطناعي:*\n"
        "التحليل يساعد في فهم حركة السوق ولا يعد توصية بيع أو شراء."
    )

# ==========================
# Webhook
# ==========================

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(force=True, silent=True)
    logging.info(update)

    if not update or "message" not in update:
        return "OK", 200

    msg = update["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()

    if text.startswith("/start"):
        send_message(chat_id,
            "👋 أهلاً بك.\nاكتب `/coin btcusdt` أو `/btc` لتحليل أي عملة.")
        return "OK", 200

    if text.startswith("/"):
        parts = text[1:].split()
        cmd = parts[0].lower()

        # لو كتب /btc
        if cmd == "coin":
            if len(parts) < 2:
                send_message(chat_id, "❗ استخدم: `/coin btcusdt`")
                return "OK", 200
            user_symbol = parts[1]
        else:
            user_symbol = cmd

        symbol = user_symbol.replace("/", "").upper()
        if not symbol.endswith("USDT"):
            symbol += "USDT"

        try:
            if symbol == "VAIUSDT":
                price = get_kucoin_last_price()
                text_reply = build_analysis(symbol, last_price=price, is_vai=True)
                send_message(chat_id, text_reply)
                return "OK", 200

            candles = get_binance_klines(symbol)
            last_close = candles[-1]["close"]
            text_reply = build_analysis(symbol, candles=candles, last_price=last_close)
            send_message(chat_id, text_reply)
            return "OK", 200

        except Exception as e:
            logging.error(e)
            send_message(chat_id, "⚠️ خطأ في جلب البيانات. تأكد من الرمز.")
            return "OK", 200

    send_message(chat_id, "ℹ️ استخدم: `/btc` أو `/coin btcusdt`")
    return "OK", 200

# ==========================
# ضبط Webhook تلقائياً
# ==========================

def set_webhook():
    url = f"{TELEGRAM_API_URL}/setWebhook"
    webhook_url = APP_BASE_URL.rstrip("/") + "/webhook"
    requests.get(url, params={"url": webhook_url})

if __name__ == "__main__":
    logging.info("Bot is running...")
    set_webhook()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
