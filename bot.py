import os
import logging
import math
import threading
import time
from datetime import datetime
from flask import Flask, request
import requests

# ==========================
# إعدادات أساسية
# ==========================

# لازم تكون ضايف TELEGRAM_TOKEN و APP_BASE_URL من Environment فى Koyeb
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
APP_BASE_URL = os.getenv("APP_BASE_URL")  # مثال: https://ugliest-tilda-in-crypto-133f2e26.koyeb.app

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN غير موجود فى Environment على Koyeb.")

if not APP_BASE_URL:
    raise RuntimeError("APP_BASE_URL غير موجود فى Environment على Koyeb.")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# آى دى الشات اللى هيوصل له تنبيه البيتكوين (حاليًا انت)
OWNER_CHAT_ID = 669209875

BINANCE_API = "https://api.binance.com"
KUCOIN_API = "https://api.kucoin.com"

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# متغيرات خاصة بالتنبيه التلقائى
LAST_BTC_ALERT_STATE = None  # "normal" / "warning"
LAST_BTC_ALERT_TS = 0        # آخر وقت تم إرسال تنبيه فيه (epoch seconds)
BTC_ALERT_COOLDOWN = 60 * 60  # لا يرسل تنبيه جديد أقل من ساعة بين كل تنبيه


# ==========================
# دوال مساعدة عامة
# ==========================

def fmt_price(p: float) -> str:
    """
    تنسيق السعر بشكل احترافي:
    - لو السعر >= 1000  => 98.000
    - من 1 إلى أقل من 1000 => 98.25
    - أقل من 1 => 0.012345
    """
    if p is None or math.isnan(p):
        return "غير متاح"
    try:
        if p >= 1000:
            s = f"{p:,.0f}"
            s = s.replace(",", ".")
            return s
        elif p >= 1:
            s = f"{p:.2f}".rstrip("0").rstrip(".")
            return s
        else:
            s = f"{p:.6f}".rstrip("0").rstrip(".")
            return s
    except Exception:
        return str(p)


def send_message(chat_id: int, text: str):
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        r = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload, timeout=10)
        if r.status_code != 200:
            logging.error(f"send_message error: {r.status_code} - {r.text}")
    except Exception as e:
        logging.error(f"Error sending message: {e}")


# ==========================
# جلب البيانات من البورصات
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
            "volume": float(c[5]),
        })
    return candles


def get_kucoin_last_price(symbol: str = "VAI-USDT") -> float:
    url = f"{KUCOIN_API}/api/v1/market/orderbook/level1"
    params = {"symbol": symbol}
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        raise ValueError(f"KuCoin error: {r.text}")
    j = r.json()
    if j.get("code") != "200000":
        raise ValueError(f"KuCoin bad response: {j}")
    return float(j["data"]["price"])


# ==========================
# مؤشرات فنية بسيطة
# ==========================

def ema(values, period: int):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema_val = sum(values[:period]) / period
    for price in values[period:]:
        ema_val = price * k + ema_val * (1 - k)
    return ema_val


def rsi(values, period: int = 14):
    if len(values) <= period:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = values[i] - values[i - 1]
        gains.append(diff if diff >= 0 else 0)
        losses.append(-diff if diff < 0 else 0)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
    # ==========================
# رصد شكل حركة السعر
# ==========================

def detect_price_structure(closes):
    if len(closes) < 30:
        return "لا توجد بيانات كافية لرصد نموذج سعري واضح حتى الآن."

    recent = closes[-30:]
    start = recent[0]
    end = recent[-1]
    change_pct = (end - start) / start * 100 if start != 0 else 0

    high = max(recent)
    low = min(recent)
    range_pct = (high - low) / low * 100 if low != 0 else 0

    if abs(change_pct) < 3 and range_pct < 8:
        return "السعر يتحرك في نطاق عرضي ضيق نسبيًا مع تذبذب محدود."
    elif change_pct > 3 and range_pct < 15:
        return "السعر يتحرك في مسار صاعد معتدل مع قمم وقيعان أعلى تدريجيًا."
    elif change_pct < -3 and range_pct < 15:
        return "السعر يتحرك في مسار هابط معتدل مع قمم وقيعان أدنى تدريجيًا."
    elif range_pct >= 15 and change_pct > 0:
        return "السعر داخل قناة سعرية صاعدة واسعة نسبيًا خلال الفترة الماضية."
    elif range_pct >= 15 and change_pct < 0:
        return "السعر داخل قناة سعرية هابطة واسعة نسبيًا مع ضغوط بيعية متكررة."
    else:
        return "الحركة السعرية متذبذبة بدون نموذج واضح، ويُفضَّل انتظار مزيد من التأكيد."


# ==========================
# بناء رسالة التحليل /coin
# ==========================

def build_analysis_text(symbol_display: str, candles=None, last_price: float = None, is_vai: bool = False):

    if is_vai:
        price_txt = fmt_price(last_price) if last_price is not None else "غير متاح"
        return (
            f"📊 *تحليل مبسط لعملة* `{symbol_display}`\n\n"
            f"💰 *السعر الحالي:* `{price_txt}`\n\n"
            "🔎 السعر يتم جلبه من *KuCoin* مع توفر بيانات تاريخية محدودة.\n"
            "لذلك التحليل الفني يكون محدود ويُفضل إدارة مخاطرة منخفضة.\n\n"
            "🤖 *ملاحظة من الذكاء الاصطناعي:* العملات الضعيفة تتحرك بقوة، فالتزم بإدارة رأس المال."
        )

    if not candles or len(candles) < 20:
        price_txt = fmt_price(last_price) if last_price is not None else "غير متاح"
        return (
            f"📊 *تحليل العملة* `{symbol_display}`\n\n"
            f"💰 *السعر الحالي:* `{price_txt}`\n\n"
            "لا توجد بيانات كافية لبناء تحليل فني يومي.\n"
            "يفضل الانتظار حتى تكون حركة أوضح.\n\n"
            "🤖 *ملاحظة:* البيانات القليلة تقلل دقة التحليل."
        )

    closes = [c['close'] for c in candles]
    last_candle = candles[-1]
    prev_candle = candles[-2]

    last_close = last_candle['close']
    prev_close = prev_candle['close']
    change_pct = (last_close - prev_close) / prev_close * 100 if prev_close != 0 else 0

    recent = candles[-30:]
    support = min([c['low'] for c in recent])
    resistance = max([c['high'] for c in recent])

    ema_fast = ema(closes, 9)
    ema_slow = ema(closes, 21)
    rsi_val = rsi(closes, 14)
    structure_text = detect_price_structure(closes)

    # الاتجاه العام
    if ema_fast and ema_slow:
        if ema_fast > ema_slow and last_close > ema_fast:
            trend_text = "الاتجاه يميل للصعود أعلى المتوسطات."
        elif ema_fast < ema_slow and last_close < ema_slow:
            trend_text = "الاتجاه يميل للهبوط أسفل المتوسطات."
        else:
            trend_text = "الاتجاه حيادي بسبب تذبذب السعر."
    else:
        trend_text = "لا توجد بيانات كافية لتحديد الاتجاه."

    # RSI
    if rsi_val is None:
        rsi_text = "مؤشر RSI غير متاح."
    elif rsi_val > 70:
        rsi_text = f"RSI `{rsi_val:.1f}` → تشبع شرائي."
    elif rsi_val < 30:
        rsi_text = f"RSI `{rsi_val:.1f}` → تشبع بيعي وفرص ارتداد محتملة."
    else:
        rsi_text = f"RSI `{rsi_val:.1f}` → حيادي."

    price_txt = fmt_price(last_close)
    support_txt = fmt_price(support)
    resistance_txt = fmt_price(resistance)

    return (
        f"📊 *تحليل فني يومي للعملة* `{symbol_display}`\n\n"
        f"💰 *السعر الحالي:* `{price_txt}`\n"
        f"📈 *تغير اليوم:* `{change_pct:.2f}%`\n\n"
        f"🎯 *حركة السعر:* \n- {structure_text}\n\n"
        f"📍 *مستويات مهمة:*\n- دعم: `{support_txt}`\n- مقاومة: `{resistance_txt}`\n\n"
        f"📊 *الاتجاه والمتوسطات:*\n- {trend_text}\n\n"
        f"📉 *مؤشر RSI:*\n- {rsi_text}\n\n"
        "🤖 هذا التحليل يعتمد على البيانات اليومية ومؤشرات مبسطة."
    )


# ==========================
# تقرير البيتكوين + التحذير الذكي
# ==========================

def build_btc_market_report(candles):

    closes = [c["close"] for c in candles]
    last = candles[-1]["close"]
    prev = candles[-2]["close"]
    change_pct = (last - prev) / prev * 100 if prev else 0

    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    rsi_val = rsi(closes, 14)

    recent = candles[-30:]
    recent_high = max([c["high"] for c in recent])
    recent_low = min([c["low"] for c in recent])

    price_txt = fmt_price(last)
    rh = fmt_price(recent_high)
    rl = fmt_price(recent_low)

    today = datetime.utcnow().strftime("%Y-%m-%d")

    if rsi_val < 30:
        rsi_desc = f"RSI `{rsi_val:.1f}` → تشبع بيعي قوي."
    elif rsi_val > 70:
        rsi_desc = f"RSI `{rsi_val:.1f}` → تشبع شرائي."
    else:
        rsi_desc = f"RSI `{rsi_val:.1f}` → حيادي."

    # الاتجاه من المتوسطات
    if ema50 and ema200:
        if last < ema50 < ema200:
            trend_desc = "السعر أسفل المتوسطات → اتجاه هابط."
        elif last > ema50 > ema200:
            trend_desc = "السعر أعلى المتوسطات → إيجابية."
        else:
            trend_desc = "السعر قرب المتوسطات → حيادي."
    else:
        trend_desc = "لا يمكن تحديد الاتجاه."

    if change_pct <= -5:
        move_desc = f"هبوط قوي `{change_pct:.2f}%`."
    elif change_pct >= 5:
        move_desc = f"صعود قوي `{change_pct:.2f}%`."
    else:
        move_desc = f"تغير اليوم `{change_pct:.2f}%`."

    return (
        f"تصحيح تاريخ التحليل ✅\n\n"
        f"🧭 *تحليل الذكاء الاصطناعي للبيتكوين* – {today}\n\n"
        f"💰 السعر الآن: `{price_txt}`\n"
        f"📉 حركة اليوم: {move_desc}\n"
        f"النطاق الحالي بين `{rl}` و `{rh}`\n\n"
        f"📊 المؤشرات:\n- {rsi_desc}\n- {trend_desc}\n\n"
        f"🔎 المقاومة والدعم:\n- دعم: `{rl}`\n- مقاومة: `{rh}`\n\n"
        f"⚠️ *رسالة IN CRYPTO Ai:*\n"
        f"السوق حساس الآن—يرجى إدارة رأس المال بحكمة."
    )


# ==========================
# تنبيه البيتكوين الذكي
# ==========================

def analyze_btc_for_alert(candles):

    closes = [c["close"] for c in candles]
    last = closes[-1]
    prev = closes[-2]
    change_pct = (last - prev) / prev * 100 if prev else 0

    rsi_val = rsi(closes, 14)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    reason = None

    if rsi_val < 30 and change_pct < -2:
        reason = "تشبع بيعي مع هبوط يومي واضح."
    elif change_pct <= -5:
        reason = "هبوط حاد يتجاوز 5%."
    elif ema50 and ema200 and last < ema50 < ema200 and change_pct < -2:
        reason = "كسر سلبي أسفل المتوسطات."

    if not reason:
        return False, None, None

    report = build_btc_market_report(candles)

    alert = (
        "\n\n⚠️ *تنبيه من IN CRYPTO Ai:*\n"
        "> تم رصد حالة خطر محتملة في حركة البيتكوين.\n"
        f"{reason}\n"
        "ننصح بتقليل المخاطرة وإدارة رأس المال."
    )

    return True, reason, report + alert


# ==========================
# حلقة مراقبة البيتكوين
# ==========================

def btc_monitor_loop():
    global LAST_BTC_ALERT_STATE, LAST_BTC_ALERT_TS

    while True:
        try:
            candles = get_binance_klines("BTCUSDT", limit=200)
            should_alert, reason, text = analyze_btc_for_alert(candles)

            now = time.time()

            if should_alert:
                if LAST_BTC_ALERT_STATE != "warning" or (now - LAST_BTC_ALERT_TS) > BTC_ALERT_COOLDOWN:
                    send_message(OWNER_CHAT_ID, text)
                    LAST_BTC_ALERT_STATE = "warning"
                    LAST_BTC_ALERT_TS = now
            else:
                LAST_BTC_ALERT_STATE = "normal"

        except Exception as e:
            logging.error(f"BTC monitor error: {e}")

        time.sleep(1800)
        # ==========================
# Webhook
# ==========================

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        update = request.get_json(force=True, silent=True)
        logging.info(f"Update: {update}")

        if not update or "message" not in update:
            return "OK", 200

        message = update["message"]
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        text = message.get("text", "").strip()

        if not chat_id or not text:
            return "OK", 200

        # /start
        if text.startswith("/start"):
            welcome = (
                "👋 أهلاً بك في بوت *IN CRYPTO Ai*.\n\n"
                "يمكنك طلب تحليل فني لأي عملة:\n"
                "› `/coin btcusdt`\n"
                "› `/btc`\n\n"
                "🔔 البوت يراقب البيتكوين تلقائيًا وسيُرسل لك تقرير + تحذير عند وجود خطر. 🤖"
            )
            send_message(chat_id, welcome)
            return "OK", 200

        # لو أمر مكتوب
        if text.startswith("/"):
            parts = text[1:].split()
            if not parts:
                send_message(chat_id, "❗ اكتب الرمز بعد الأمر، مثال: `/coin btcusdt`")
                return "OK", 200

            cmd = parts[0].lower()

            # تقرير BTC يدوي
            if cmd in ("btc_report", "btcreport"):
                try:
                    candles = get_binance_klines("BTCUSDT", limit=200)
                    report = build_btc_market_report(candles)
                    send_message(chat_id, report)
                except Exception as e:
                    logging.error(e)
                    send_message(chat_id, "⚠️ تعذّر إنشاء التقرير الآن.")
                return "OK", 200

            # أمر coin
            if cmd == "coin":
                if len(parts) < 2:
                    send_message(chat_id, "❗ مثال: `/coin ethusdt`")
                    return "OK", 200
                user_symbol = parts[1]
            else:
                # مثل /btc أو /eth
                user_symbol = cmd

            # تنظيف الرمز
            user_symbol_clean = user_symbol.replace("/", "").replace(" ", "").upper()
            if not user_symbol_clean.endswith("USDT"):
                user_symbol_clean = user_symbol_clean.replace("USDT", "") + "USDT"

            symbol_display = user_symbol_clean

            try:
                # لو VAI من KuCoin
                if user_symbol_clean in ("VAIUSDT", "VAI-USDT"):
                    last_price = get_kucoin_last_price("VAI-USDT")
                    text_reply = build_analysis_text(symbol_display, candles=None, last_price=last_price, is_vai=True)
                    send_message(chat_id, text_reply)
                    return "OK", 200

                # باقي العملات من Binance
                candles = get_binance_klines(user_symbol_clean, limit=120)
                last_close = candles[-1]["close"] if candles else None
                text_reply = build_analysis_text(symbol_display, candles=candles, last_price=last_close)
                send_message(chat_id, text_reply)
                return "OK", 200

            except Exception as e:
                logging.error(e)
                send_message(chat_id, "⚠️ لا يمكن جلب بيانات العملة الآن.")
                return "OK", 200

        # أي رسالة غير الأوامر
        send_message(
            chat_id,
            "ℹ️ استخدم:\n`/coin btcusdt`\nأو `/btc`"
        )
        return "OK", 200

    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return "OK", 200


# ==========================
# إعداد Webhook + تشغيل السيرفر
# ==========================

def setup_webhook():
    webhook_url = APP_BASE_URL.rstrip("/") + "/webhook"
    url = f"{TELEGRAM_API_URL}/setWebhook"
    try:
        r = requests.get(url, params={"url": webhook_url}, timeout=10)
        logging.info(f"Webhook response: {r.status_code} - {r.text}")
    except Exception as e:
        logging.error(f"Webhook setup error: {e}")


def start_btc_monitor_thread():
    t = threading.Thread(target=btc_monitor_loop, daemon=True)
    t.start()
    logging.info("BTC monitor thread started.")


if __name__ == "__main__":
    logging.info("Bot is starting...")
    setup_webhook()
    start_btc_monitor_thread()

    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
