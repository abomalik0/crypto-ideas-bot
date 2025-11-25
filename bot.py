import os
import logging
import math
from flask import Flask, request
import requests

# ==========================
# قراءة التوكن والهوست من ENV
# ==========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
APP_BASE_URL = os.getenv("APP_BASE_URL")

if not BOT_TOKEN:
    raise Exception("❗ BOT_TOKEN not found in environment variables.")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

BINANCE_API = "https://api.binance.com"
KUCOIN_API = "https://api.kucoin.com"

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# ==========================
# أدوات مساعدة
# ==========================

def fmt_price(p: float) -> str:
    """تنسيق السعر بشكل مشابه للسوق الحقيقي"""
    if p is None or math.isnan(p):
        return "غير متاح"
    try:
        if p >= 1000:
            return f"{p:,.0f}".replace(",", ".")
        elif p >= 1:
            s = f"{p:.3f}".rstrip("0").rstrip(".")
            return s
        else:
            s = f"{p:.6f}".rstrip("0").rstrip(".")
            return s
    except:
        return str(p)


def send_msg(chat_id, text):
    try:
        requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        logging.error(f"Send error: {e}")


# ==========================
# Binance – شموع يومية
# ==========================

def get_klines(sym: str, limit=120):
    r = requests.get(
        f"{BINANCE_API}/api/v3/klines",
        params={"symbol": sym, "interval": "1d", "limit": limit},
        timeout=10
    )
    if r.status_code != 200:
        raise Exception(f"Binance error: {r.text}")

    out = []
    for c in r.json():
        out.append({
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
        })
    return out


def get_vai_price():
    r = requests.get(
        f"{KUCOIN_API}/api/v1/market/orderbook/level1",
        params={"symbol": "VAI-USDT"},
        timeout=10
    )
    j = r.json()
    if j.get("code") != "200000":
        raise Exception("KuCoin error")
    return float(j["data"]["price"])


# ==========================
# RSI
# ==========================

def rsi(values, period=14):
    if len(values) <= period:
        return None
    gains, losses = [], []
    for i in range(1, period+1):
        diff = values[i] - values[i-1]
        gains.append(diff if diff > 0 else 0)
        losses.append(-diff if diff < 0 else 0)

    avg_gain = sum(gains)/period
    avg_loss = sum(losses)/period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100/(1+rs))


# ==========================
# تحليل العملة – تنسيق النسخة 2
# ==========================

def build_analysis(sym, candles):
    closes = [c["close"] for c in candles]

    last = candles[-1]
    prev = candles[-2]

    price = last["close"]
    price_txt = fmt_price(price)

    change = ((price - prev["close"]) / prev["close"]) * 100
    change_txt = f"{change:.2f}%"

    recent = candles[-40:]
    support = min([c["low"] for c in recent])
    resist = max([c["high"] for c in recent])

    rsi_val = rsi(closes)

    rsi_txt = f"جيادي."
    if rsi_val < 30:
        rsi_txt = "تشبع بيعي."
    elif rsi_val > 70:
        rsi_txt = "تشبع شرائي."

    trend = ""
    if price < sum(closes[-20:])/20:
        trend = "السعر داخل مسار هابط معتدل."
    else:
        trend = "السعر يظهر محاولة إيجابية لكن بدون تأكيد."

    txt = (
        f"*📊 تحليل فني يومي للعملة {sym}*\n\n"
        f"*💰 السعر الحالي:* `{price_txt}`\n"
        f"*📉 تغيّر اليوم:* `{change_txt}`\n\n"
        f"*🎯 حركة السعر:*\n"
        f"- {trend}\n\n"
        f"*📍 مستويات مهمة:*\n"
        f"- دعم: `{fmt_price(support)}`\n"
        f"- مقاومة: `{fmt_price(resist)}`\n\n"
        f"*📉 RSI:*\n"
        f"- RSI {rsi_val:.1f} → {rsi_txt}\n\n"
        f"🤖 *ملاحظة الذكاء الاصطناعي:*\n"
        f"التحليل يساعد على فهم الاتجاه، وليس توصية بيع أو شراء."
    )

    return txt


# ==========================
# Webhook
# ==========================

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True)
    logging.info(update)

    if not update or "message" not in update:
        return "ok", 200

    msg = update["message"]
    chat = msg["chat"]["id"]
    text = msg.get("text", "").strip()

    # /start
    if text == "/start":
        send_msg(chat,
            "👋 أهلاً بك!\n"
            "اكتب `/btc` أو `/coin btcusdt` للحصول على التحليل."
        )
        return "ok", 200

    # أوامر التحليل
    if text.startswith("/"):
        parts = text[1:].split()
        cmd = parts[0].lower()

        if cmd == "coin":
            if len(parts) < 2:
                send_msg(chat, "❗ استخدم: `/coin btcusdt`")
                return "ok", 200
            symbol = parts[1]
        else:
            symbol = cmd

        s = symbol.upper().replace("/", "").replace(" ", "")
        if not s.endswith("USDT"):
            s += "USDT"

        try:
            if s.startswith("VAI"):
                price = get_vai_price()
                send_msg(chat, f"سعر VAI حالياً: `{fmt_price(price)}`")
                return "ok", 200

            candles = get_klines(s)
            txt = build_analysis(s, candles)
            send_msg(chat, txt)
            return "ok", 200

        except Exception as e:
            logging.error(e)
            send_msg(chat, "⚠️ تعذّر جلب بيانات الرمز.")
            return "ok", 200

    send_msg(chat, "استخدم `/btc` أو `/coin btcusdt`")
    return "ok", 200


# ==========================
# Set Webhook on startup
# ==========================

def set_webhook():
    if not APP_BASE_URL:
        logging.error("APP_BASE_URL missing!")
        return
    url = APP_BASE_URL.rstrip("/") + "/webhook"
    r = requests.get(f"{TELEGRAM_API}/setWebhook", params={"url": url})
    logging.info(r.text)


if __name__ == "__main__":
    logging.info("Bot is starting...")
    set_webhook()
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
