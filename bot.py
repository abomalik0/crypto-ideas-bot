import os
import logging
import math
from flask import Flask, request
import requests

# ==========================
# قراءة التوكن والـ BASE URL من Environment
# ==========================

TELEGRAM_TOKEN = os.environ.get("BOT_TOKEN")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "").rstrip("/")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

BINANCE_API = "https://api.binance.com"
KUCOIN_API = "https://api.kucoin.com"

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ==========================
# تنسيق الأسعار
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

# ==========================
# إرسال الرسائل
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
# بيانات البورصات
# ==========================

def get_binance_klines(symbol: str, limit: int = 120):
    url = f"{BINANCE_API}/api/v3/klines"
    params = {"symbol": symbol, "interval": "1d", "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        raise ValueError(r.text)

    data = r.json()
    candles = []
    for c in data:
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
    j = r.json()
    if j.get("code") != "200000":
        raise ValueError(j)
    return float(j["data"]["price"])

# ==========================
# مؤشرات فنية
# ==========================

def ema(values, period: int):
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
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def detect_structure(closes):
    if len(closes) < 30:
        return "لا توجد بيانات كافية لرصد شكل الحركة العامة."
    recent = closes[-30:]
    start, end = recent[0], recent[-1]
    change_pct = (end - start) / start * 100
    high, low = max(recent), min(recent)
    range_pct = (high - low) / low * 100

    if abs(change_pct) < 3 and range_pct < 8:
        return "السعر يتحرك داخل نطاق عرضي ضيق نسبيًا."
    if change_pct > 3 and range_pct < 15:
        return "السعر يتحرك في مسار صاعد معتدل."
    if change_pct < -3 and range_pct < 15:
        return "السعر يتحرك في مسار هابط معتدل."
    if range_pct >= 15 and change_pct > 0:
        return "السعر داخل قناة سعرية صاعدة واسعة."
    if range_pct >= 15 and change_pct < 0:
        return "السعر داخل قناة سعرية هابطة واسعة."
    return "الحركة متذبذبة بدون نموذج واضح."

# ==========================
# بناء رسالة التحليل
# ==========================

def build_analysis(symbol_display, candles=None, last_price=None, is_vai=False):

    if is_vai:
        price_txt = fmt_price(last_price)
        return (
            f"📊 *تحليل مبسط لعملة* `{symbol_display}`\n\n"
            f"💰 *السعر الحالي:* `{price_txt}`\n\n"
            "🔍 لقلة البيانات من KuCoin، يتم تقديم تحليل مبسط فقط.\n"
            "ينصح بإدارة مخاطر حذرة.\n\n"
            "🤖 *ملاحظة من الذكاء الاصطناعي:*\n"
            "السيولة المحدودة قد تسبب حركة سعرية حادة، الأفضل التداول بحجم صغير."
        )

    closes = [c["close"] for c in candles]
    last_close = closes[-1]
    prev_close = closes[-2]
    change_pct = (last_close - prev_close) / prev_close * 100

    recent = candles[-30:]
    support = min([c["low"] for c in recent])
    resistance = max([c["high"] for c in recent])

    ema_fast = ema(closes, 9)
    ema_slow = ema(closes, 21)
    rsi_val = rsi(closes)
    structure = detect_structure(closes)

    if ema_fast and ema_slow:
        if ema_fast > ema_slow and last_close > ema_fast:
            trend = "الاتجاه العام يميل للصعود."
        elif ema_fast < ema_slow and last_close < ema_slow:
            trend = "الاتجاه العام يميل للهبوط."
        else:
            trend = "الاتجاه العام حيادي نسبيًا."
    else:
        trend = "لا توجد بيانات كافية لتحديد الاتجاه."

    if rsi_val > 70:
        rsi_txt = f"RSI {rsi_val:.1f} → *تشبع شرائي*."
    elif rsi_val < 30:
        rsi_txt = f"RSI {rsi_val:.1f} → *تشبع بيعي*."
    else:
        rsi_txt = f"RSI {rsi_val:.1f} → حيادي."

    return (
        f"📊 *تحليل فني يومي للعملة* `{symbol_display}`\n\n"
        f"💰 *السعر الحالي:* `{fmt_price(last_close)}`\n"
        f"📈 *تغير اليوم:* `{change_pct:.2f}%`\n\n"
        f"🧭 *حركة السعر:*\n- {structure}\n\n"
        f"📍 *مستويات فنية:*\n- دعم: `{fmt_price(support)}`\n- مقاومة: `{fmt_price(resistance)}`\n\n"
        f"📊 *الاتجاه والمتوسطات:*\n- {trend}\n\n"
        f"📉 *RSI:*\n- {rsi_txt}\n\n"
        "🤖 *ملاحظة الذكاء الاصطناعي:*\n"
        "هذا تحليل تلقائي للتوعية فقط، وليس توصية مباشرة."
    )

# ==========================
# Webhook
# ==========================

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        update = request.get_json(force=True)
        logging.info(update)

        if "message" not in update:
            return "OK", 200

        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "").strip()

        if text.startswith("/start"):
            send_message(chat_id,
                "👋 أهلاً بك!\n\n"
                "اكتب:\n`/coin btcusdt`\nأو ببساطة:\n`/btc`"
            )
            return "OK", 200

        if text.startswith("/"):
            parts = text[1:].split()
            cmd = parts[0].lower()

            if cmd == "coin":
                if len(parts) < 2:
                    send_message(chat_id, "اكتب `/coin btcusdt`")
                    return "OK", 200
                sym = parts[1]
            else:
                sym = cmd

            user_symbol = sym.upper().replace("/", "")
            if not user_symbol.endswith("USDT"):
                user_symbol += "USDT"

            if user_symbol == "VAIUSDT":
                price = get_kucoin_last_price("VAI-USDT")
                send_message(chat_id, build_analysis("VAIUSDT", None, price, True))
                return "OK", 200

            candles = get_binance_klines(user_symbol)
            last_close = candles[-1]["close"]
            send_message(chat_id, build_analysis(user_symbol, candles, last_close))

        return "OK", 200

    except Exception as e:
        logging.error(e)
        return "OK", 200

# ==========================
# Set Webhook تلقائيًا
# ==========================

def setup_webhook():
    url = f"{TELEGRAM_API_URL}/setWebhook"
    webhook_url = APP_BASE_URL + "/webhook"
    try:
        r = requests.get(url, params={"url": webhook_url})
        logging.info(r.text)
    except:
        pass

if __name__ == "__main__":
    setup_webhook()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
