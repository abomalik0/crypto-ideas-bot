import os
import logging
from flask import Flask, request
import requests

# ==============================
#      الإعدادات العامة
# ==============================

TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
APP_URL = os.getenv("APP_URL")

if not TELEGRAM_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN مش موجود فى الـ Environment.")

if not APP_URL:
    raise RuntimeError("❌ APP_URL مش موجود فى الـ Environment.")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# ==============================
#     روابط Binance + KuCoin
# ==============================

BINANCE_API = "https://api.binance.com"
KUCOIN_API = "https://api.kucoin.com"


# ==============================
#     إرسال رسالة لتليجرام
# ==============================

def send_message(chat_id: int, text: str, parse_mode="HTML"):
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Send message error: {e}")


# ==============================
#   توحيد شكل الرمز normalize
# ==============================

def normalize_symbol(user_symbol: str) -> str:
    """
    توحيد الرمز:
    - تشيل / والمسافات
    - تضيف USDT لو مش موجودة
    """
    clean = user_symbol.upper().replace("/", "").replace(" ", "")
    if not clean.endswith("USDT"):
        clean = clean.replace("USDT", "")
        clean = clean + "USDT"
    return clean


# ==============================
#  جلب بيانات السعر (Binance + KuCoin)
# ==============================

def fetch_price_data(symbol: str):
    """
    ترجع dict متكاملة:
    - lastPrice
    - priceChangePercent (إن وجد)
    - exchange
    - symbol
    """

    # 1) التطبيع
    norm = normalize_symbol(symbol)

    # 2) VAI → KuCoin فقط
    if norm in ("VAIUSDT", "VAI-USDT"):
        try:
            r = requests.get(
                f"{KUCOIN_API}/api/v1/market/orderbook/level1",
                params={"symbol": "VAI-USDT"},
                timeout=10,
            )
            j = r.json()
            if j.get("code") != "200000":
                logging.error(f"KuCoin error: {j}")
                return None

            return {
                "symbol": "VAIUSDT",
                "exchange": "KuCoin",
                "lastPrice": float(j["data"]["price"]),
                "priceChangePercent": None,
            }
        except Exception as e:
            logging.error(f"VAI exception: {e}")
            return None

    # 3) باقي الرموز من Binance
    try:
        url = f"{BINANCE_API}/api/v3/ticker/24hr"
        r = requests.get(url, params={"symbol": norm}, timeout=10)
        if r.status_code != 200:
            logging.error(f"Binance error {r.status_code}: {r.text}")
            return None

        data = r.json()
        data["symbol"] = data.get("symbol", norm)
        data["exchange"] = "Binance"
        return data

    except Exception as e:
        logging.error(f"fetch_price_data error: {e}")
        return None


# ==============================
#      بناء رسالة التحليل
# ==============================

def format_analysis(symbol: str):
    data = fetch_price_data(symbol)

    if not data:
        return (
            "⚠️ لم يتم العثور على بيانات موثوقة لهذه العملة.\n"
            "✅ تأكد من الرمز مثل:\n"
            "`/coin btcusdt`\n"
            "`/coin cfxusdt`\n"
            "`/coin vai`"
        )

    price = float(data["lastPrice"])

    raw_change = data.get("priceChangePercent")
    change = None
    if raw_change not in (None, "", "0", "0.0", "0.000"):
        try:
            change = float(raw_change)
        except:
            change = None

    symbol_final = data["symbol"]
    exchange = data["exchange"]

    # دعم و مقاومة تقديري
    support = round(price * 0.92, 4)
    resistance = round(price * 1.12, 4)

    # RSI تقديري
    if change is not None:
        rsi = round(45 + (change % 10), 1)
        rsi_trend = "🔼 صعودي" if rsi > 50 else "🔽 هابط"
    else:
        rsi = None
        rsi_trend = "⚪ لا يمكن حساب RSI لعدم توفر بيانات تغيير يومية."

    # اتجاه
    if change is None:
        trend = "↔️ الاتجاه غير محدد لعدم توفر بيانات التغير."
        change_line = "📉 *تغير اليوم:* غير متاح."
    else:
        trend = "↗️ الاتجاه يميل للصعود." if change > 0 else "↘️ الاتجاه يميل للهبوط."
        change_line = f"📉 *تغير اليوم:* %{change:.2f}"

    price_str = f"{price:,.6f}".rstrip("0").rstrip(".")

    # توضيح مصدر VAI
    source_note = ""
    if exchange == "KuCoin" and symbol_final.startswith("VAI"):
        source_note = "\n📌 *ملاحظة:* سعر VAI يتم جلبه من KuCoin."

    return f"""
📊 <b>تحليل فني يومي للعملة {symbol_final}</b>

💰 <b>السعر الحالي:</b> {price_str}$
{change_line}

🎯 <b>حركة السعر:</b>
- {trend}

📍 <b>مستويات فنية تقديرية:</b>
- دعم: {support}
- مقاومة: {resistance}

📉 <b>RSI:</b>
- {rsi if rsi is not None else 'غير متاح'} → {rsi_trend}

🤖 <b>ملاحظة الذكاء الاصطناعي:</b>
التحليل مبسط بناءً على بيانات يومية عامة، ولا يُعتبر توصية مباشرة.
{source_note}
    """.strip()


# ==============================
#          Webhook
# ==============================

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()

    if not update or "message" not in update:
        return "OK"

    msg = update["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip().lower()

    # /start
    if text == "/start":
        send_message(
            chat_id,
            "أهلاً بك 👋\n"
            "اكتب /btc أو /coin btcusdt للحصول على التحليل."
        )
        return "OK"

    # /btc
    if text == "/btc":
        reply = format_analysis("BTCUSDT")
        send_message(chat_id, reply)
        return "OK"

    # /coin xxx
    if text.startswith("/coin"):
        parts = text.split()
        if len(parts) < 2:
            send_message(chat_id, "⚠️ مثال: /coin cfx أو /coin btcusdt")
        else:
            symbol = parts[1]
            reply = format_analysis(symbol)
            send_message(chat_id, reply)
        return "OK"

    return "OK"


# ==============================
#      تشغيل Flask على port 8080
# ==============================

if __name__ == "__main__":
    print("Bot is running...")
    app.run(host="0.0.0.0", port=8080)
