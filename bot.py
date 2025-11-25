import os
import logging
import math
from flask import Flask, request
import requests

# ==========================
# إعدادات تتم قراءتها من Environment
# ==========================
TELEGRAM_TOKEN = os.environ.get("BOT_TOKEN")
APP_BASE_URL = os.environ.get("APP_BASE_URL")

if not TELEGRAM_TOKEN:
    raise ValueError("❌ BOT_TOKEN غير موجود في Environment Variables")

if not APP_BASE_URL:
    raise ValueError("❌ APP_BASE_URL غير موجود في Environment Variables")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

BINANCE_API = "https://api.binance.com"
KUCOIN_API = "https://api.kucoin.com"

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ==========================
# أدوات تنسيق
# ==========================

def fmt_price(p: float) -> str:
    if p is None or math.isnan(p):
        return "غير متاح"
    try:
        if p >= 1000:
            s = f"{p:,.0f}".replace(",", ".")
            return s
        elif p >= 1:
            return f"{p:.2f}".rstrip("0").rstrip(".")
        else:
            return f"{p:.6f}".rstrip("0").rstrip(".")
    except Exception:
        return str(p)


def send_message(chat_id: int, text: str):
    try:
        requests.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        logging.error(f"Error sending message: {e}")


# ==========================
# جلب بيانات البورصات
# ==========================

def get_binance_klines(symbol: str, limit: int = 120):
    url = f"{BINANCE_API}/api/v3/klines"
    r = requests.get(url, params={"symbol": symbol, "interval": "1d", "limit": limit}, timeout=10)

    if r.status_code != 200:
        raise ValueError(f"Binance error: {r.text}")

    candles = []
    for c in r.json():
        candles.append({
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "volume": float(c[5]),
        })
    return candles


def get_kucoin_last_price(symbol="VAI-USDT"):
    url = f"{KUCOIN_API}/api/v1/market/orderbook/level1"
    r = requests.get(url, params={"symbol": symbol}, timeout=10)

    data = r.json()
    if data.get("code") != "200000":
        raise ValueError("Bad KuCoin response")

    return float(data["data"]["price"])


# ==========================
# مؤشرات فنية بسيطة
# ==========================

def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema_v = sum(values[:period]) / period
    for p in values[period:]:
        ema_v = p * k + ema_v * (1 - k)
    return ema_v


def rsi(values, period=14):
    if len(values) <= period:
        return None

    gains, losses = [], []
    for i in range(1, period + 1):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def detect_price_structure(closes):
    if len(closes) < 30:
        return "لا توجد بيانات كافية لرصد نموذج سعري واضح."

    rec = closes[-30:]
    start, end = rec[0], rec[-1]

    change = (end - start) / start * 100 if start else 0
    high, low = max(rec), min(rec)
    rng = (high - low) / low * 100 if low else 0

    if abs(change) < 3 and rng < 8:
        return "السعر يتحرك في نطاق عرضي ضيق نسبيًا."
    if change > 3 and rng < 15:
        return "السعر يتحرك في مسار صاعد معتدل."
    if change < -3 and rng < 15:
        return "السعر يتحرك في مسار هابط معتدل."
    if rng >= 15 and change > 0:
        return "قناة سعرية صاعدة واسعة نسبيًا."
    if rng >= 15 and change < 0:
        return "قناة سعرية هابطة واسعة نسبيًا."
    return "الحركة متذبذبة وغير واضحة."


# ==========================
# بناء النص النهائي للتحليل
# ==========================

def build_analysis(symbol, candles=None, last_price=None, is_vai=False):

    if is_vai:
        return (
            f"📊 *تحليل مبسط لعملة* `{symbol}`\n\n"
            f"💰 *السعر الحالي:* `{fmt_price(last_price)}`\n\n"
            "🔹 بيانات VAI محدودة — التحليل مبسط فقط.\n"
            "🔹 يفضل تداولها بحجم مخاطرة منخفض.\n\n"
            "🤖 *تنبيه الذكاء الاصطناعي:*\n"
            "السيولة منخفضة وحركة السعر قد تكون حادة."
        )

    if not candles:
        return f"لا توجد بيانات كافية لعملة {symbol}"

    closes = [c["close"] for c in candles]
    last_c = candles[-1]
    prev_c = candles[-2]

    change_pct = (last_c["close"] - prev_c["close"]) / prev_c["close"] * 100

    rec = candles[-30:]
    support = min([c["low"] for c in rec])
    resistance = max([c["high"] for c in rec])

    ema_fast = ema(closes, 9)
    ema_slow = ema(closes, 21)

    rsi_v = rsi(closes)

    # اتجاه عام
    if ema_fast and ema_slow:
        if ema_fast > ema_slow and last_c["close"] > ema_fast:
            trend = "الاتجاه العام صاعد نسبيًا."
        elif ema_fast < ema_slow and last_c["close"] < ema_slow:
            trend = "الاتجاه العام هابط."
        else:
            trend = "الاتجاه العام حيادي."
    else:
        trend = "غير كافٍ لتحديد اتجاه واضح."

    # RSI
    if rsi_v is None:
        rsi_text = "غير متاح."
    elif rsi_v > 70:
        rsi_text = f"{rsi_v:.1f} → تشبع شرائي."
    elif rsi_v < 30:
        rsi_text = f"{rsi_v:.1f} → تشبع بيعي."
    else:
        rsi_text = f"{rsi_v:.1f} → حيادي."

    return (
        f"📊 *تحليل {symbol} — يومي*\n\n"
        f"💰 السعر الحالي: `{fmt_price(last_c['close'])}`\n"
        f"📈 تغيير اليوم: `{change_pct:.2f}%`\n\n"
        f"🧭 الاتجاه والسلوك:\n"
        f"- {trend}\n"
        f"- {detect_price_structure(closes)}\n\n"
        f"📍 مستويات مهمة:\n"
        f"- دعم: `{fmt_price(support)}`\n"
        f"- مقاومة: `{fmt_price(resistance)}`\n\n"
        f"📉 RSI: {rsi_text}\n\n"
        "🤖 *ملاحظة الذكاء الاصطناعي:*\n"
        "هذا تحليل تلقائي، وليس توصية مباشرة."
    )


# ==========================
# Webhook
# ==========================

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)

    if not data or "message" not in data:
        return "OK", 200

    msg = data["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()

    if text.startswith("/start"):
        send_message(chat_id,
                     "👋 أهلاً بك!\nاكتب `/btc` أو `/coin btcusdt` للحصول على التحليل.")
        return "OK", 200

    if text.startswith("/"):
        cmd = text[1:].split()
        sym = cmd[0].upper()

        if sym == "COIN":
            if len(cmd) < 2:
                send_message(chat_id, "❗ اكتب `/coin btcusdt`")
                return "OK", 200
            sym = cmd[1].upper()

        if not sym.endswith("USDT"):
            sym = sym.replace("USDT", "") + "USDT"

        try:
            if sym.startswith("VAI"):
                price = get_kucoin_last_price()
                send_message(chat_id, build_analysis(sym, None, price, True))
                return "OK", 200

            candles = get_binance_klines(sym)
            send_message(chat_id, build_analysis(sym, candles))
            return "OK", 200

        except Exception:
            send_message(chat_id, "⚠️ لا يمكن جلب بيانات هذه العملة الآن.")
            return "OK", 200

    send_message(chat_id, "اكتب `/btc` أو `/coin btcusdt`")
    return "OK", 200


# ==========================
# Setup Webhook تلقائيًا
# ==========================

def setup_webhook():
    url = f"{TELEGRAM_API_URL}/setWebhook"
    webhook_url = APP_BASE_URL.rstrip("/") + "/webhook"
    requests.get(url, params={"url": webhook_url}, timeout=10)
    logging.info("Webhook set:", webhook_url)


if __name__ == "__main__":
    setup_webhook()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
