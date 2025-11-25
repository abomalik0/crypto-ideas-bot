import os
import logging
import math
from flask import Flask, request
import requests

# ==========================
# قراءة المتغيرات من Environment
# ==========================
TELEGRAM_TOKEN = os.environ.get("BOT_TOKEN")
APP_BASE_URL = os.environ.get("APP_BASE_URL")

if not TELEGRAM_TOKEN:
    raise ValueError("❌ BOT_TOKEN not found in environment variables")

if not APP_BASE_URL:
    raise ValueError("❌ APP_BASE_URL not found in environment variables")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
BINANCE_API = "https://api.binance.com"
KUCOIN_API = "https://api.kucoin.com"

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
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
            s = f"{p:.2f}".rstrip("0").rstrip(".")
            return s
        else:
            s = f"{p:.6f}".rstrip("0").rstrip(".")
            return s
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
            "parse_mode": "Markdown"
        }
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Error sending message: {e}")


# ==========================
# جلب بيانات باينانس
# ==========================
def get_binance_klines(symbol: str, limit: int = 120):
    url = f"{BINANCE_API}/api/v3/klines"
    params = {"symbol": symbol, "interval": "1d", "limit": limit}
    r = requests.get(url, params=params, timeout=10)

    if r.status_code != 200:
        raise ValueError(f"Binance error: {r.text}")

    data = r.json()
    candles = []

    for c in data:
        candles.append({
            "open_time": c[0],
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "volume": float(c[5])
        })

    return candles


# ==========================
# جلب سعر VAI من KuCoin
# ==========================
def get_kucoin_last_price(symbol="VAI-USDT"):
    url = f"{KUCOIN_API}/api/v1/market/orderbook/level1"
    r = requests.get(url, params={"symbol": symbol}, timeout=10)

    if r.status_code != 200:
        raise ValueError(r.text)

    j = r.json()

    if j.get("code") != "200000":
        raise ValueError(j)

    return float(j["data"]["price"])


# ==========================
# EMA و RSI
# ==========================
def ema(values, period: int):
    if len(values) < period:
        return None

    k = 2 / (period + 1)
    ema_val = sum(values[:period]) / period

    for price in values[period:]:
        ema_val = (price * k) + (ema_val * (1 - k))

    return ema_val


def rsi(values, period: int = 14):
    if len(values) <= period:
        return None

    gains = []
    losses = []

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
# هيكل السعر
# ==========================
def detect_price_structure(closes):
    if len(closes) < 30:
        return "لا توجد بيانات كافية لرصد نموذج سعري واضح حتى الآن."

    recent = closes[-30:]
    start, end = recent[0], recent[-1]

    change_pct = (end - start) / start * 100 if start else 0

    high = max(recent)
    low = min(recent)

    range_pct = (high - low) / low * 100 if low else 0

    if abs(change_pct) < 3 and range_pct < 8:
        return "السعر يتحرك في نطاق عرضي ضيق نسبيًا."
    elif change_pct > 3 and range_pct < 15:
        return "السعر يتحرك في مسار صاعد معتدل."
    elif change_pct < -3 and range_pct < 15:
        return "السعر يتحرك في مسار هابط معتدل."
    elif range_pct >= 15 and change_pct > 0:
        return "قناة سعرية صاعدة واسعة."
    elif range_pct >= 15 and change_pct < 0:
        return "قناة سعرية هابطة واسعة."
    else:
        return "حركة متذبذبة بدون نموذج واضح."


# ==========================
# بناء نص التحليل (نفس النسخة اللي اختبرناها)
# ==========================
def build_analysis_text(symbol_display, candles=None, last_price=None, is_vai=False):

    # معالجة VAI
    if is_vai:
        price = fmt_price(last_price)
        return (
            f"📊 *تحليل مبسط لعملة* `{symbol_display}`\n\n"
            f"💰 *السعر الحالي:* `{price}`\n\n"
            "🔎 يتم جلب البيانات من KuCoin — البيانات التاريخية محدودة لذلك التحليل مختصر.\n"
            "يُفضّل إدارة مخاطر حذرة.\n\n"
            "🤖 *ملاحظة الذكاء الاصطناعي:*\n"
            "السيولة ضعيفة – الحركة قد تكون حادة."
        )

    # لا توجد بيانات كافية
    if not candles or len(candles) < 20:
        price = fmt_price(last_price)
        return (
            f"📊 *تحليل العملة* `{symbol_display}`\n\n"
            f"💰 *السعر الحالي:* `{price}`\n\n"
            "⚠️ البيانات غير كافية لبناء تحليل قوي."
        )

    closes = [c["close"] for c in candles]
    lc = candles[-1]["close"]
    pc = candles[-2]["close"]

    change = (lc - pc) / pc * 100

    recent = candles[-30:]
    support = min([c["low"] for c in recent])
    resistance = max([c["high"] for c in recent])

    e9 = ema(closes, 9)
    e21 = ema(closes, 21)

    r = rsi(closes, 14)

    structure = detect_price_structure(closes)

    if e9 and e21:
        if e9 > e21 and lc > e9:
            trend = "الاتجاه العام يميل إلى الصعود."
        elif e9 < e21 and lc < e21:
            trend = "الاتجاه العام يميل إلى الهبوط."
        else:
            trend = "الاتجاه العام حيادي."
    else:
        trend = "لا يمكن تحديد الاتجاه."

    if r is None:
        rsi_t = "RSI غير متاح."
    elif r > 70:
        rsi_t = f"RSI {r:.1f} → تشبّع شرائي."
    elif r < 30:
        rsi_t = f"RSI {r:.1f} → تشبّع بيعي."
    else:
        rsi_t = f"RSI {r:.1f} → حيادي."

    text = (
        f"📊 *تحليل فني يومي للعملة* `{symbol_display}`\n\n"
        f"💰 *السعر الحالي:* `{fmt_price(lc)}`\n"
        f"📈 *تغير اليوم:* `{change:.2f}%`\n\n"
        f"🧭 *حركة السعر:*\n- {structure}\n\n"
        f"📍 *مستويات مهمة:*\n- دعم: `{fmt_price(support)}`\n- مقاومة: `{fmt_price(resistance)}`\n\n"
        f"📊 *الاتجاه والمتوسطات:*\n- {trend}\n\n"
        f"📉 *RSI:*\n- {rsi_t}\n\n"
        "🤖 *ملاحظة الذكاء الاصطناعي:*\n"
        "التحليل يساعد على فهم الاتجاه، وليس توصية بيع أو شراء."
    )

    return text


# ==========================
# Webhook
# ==========================
@app.route("/", methods=["GET"])
def home():
    return "Bot is running", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        update = request.get_json(force=True, silent=True)
        logging.info(update)

        if not update or "message" not in update:
            return "OK", 200

        msg = update["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "").strip()

        if text.startswith("/start"):
            send_message(
                chat_id,
                "👋 أهلاً بك!\nاكتب `/coin btcusdt` أو `/btc` للحصول على التحليل."
            )
            return "OK", 200

        if text.startswith("/"):
            parts = text[1:].split()

            if parts[0] == "coin":
                if len(parts) < 2:
                    send_message(chat_id, "❗ اكتب: `/coin btcusdt`")
                    return "OK", 200
                sym = parts[1]
            else:
                sym = parts[0]

            symbol = sym.replace("/", "").upper()
            if not symbol.endswith("USDT"):
                symbol += "USDT"

            # معالجة VAI
            if symbol in ("VAIUSDT", "VAI-USDT"):
                price = get_kucoin_last_price("VAI-USDT")
                send_message(chat_id, build_analysis_text(symbol, None, price, True))
                return "OK", 200

            candles = get_binance_klines(symbol)
            lc = candles[-1]["close"]

            text_reply = build_analysis_text(symbol, candles, lc, False)
            send_message(chat_id, text_reply)
            return "OK", 200

        send_message(chat_id, "اكتب `/btc` أو `/coin btcusdt`")
        return "OK", 200

    except Exception as e:
        logging.error(e)
        return "OK", 200


# ==========================
# تعيين الويبهوك
# ==========================
def setup_webhook():
    webhook_url = APP_BASE_URL.rstrip("/") + "/webhook"
    try:
        r = requests.post(
            f"{TELEGRAM_API_URL}/setWebhook",
            json={"url": webhook_url},
            timeout=10
        )
        logging.info(r.text)
    except Exception as e:
        logging.error(e)


if __name__ == "__main__":
    setup_webhook()
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
