import os
import logging
import math
from flask import Flask, request
import requests

# ==========================
# إعدادات أساسية
# ==========================

TELEGRAM_TOKEN = "8207052650:AAEJ7qyoWqDYyMyllsNuyZHzLynlTM4x9os"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# رابط السيرفر على Koyeb (بدون / في الآخر)
APP_BASE_URL = "https://ugliest-tilda-in-crypto-133f2e26.koyeb.app"

BINANCE_API = "https://api.binance.com"
KUCOIN_API = "https://api.kucoin.com"

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# ==========================
# دوال مساعدة عامة
# ==========================

def fmt_price(p: float) -> str:
    """
    تنسيق السعر بشكل احترافي:
    - لو السعر كبير (أكبر من أو يساوي 1000) => 98.000
    - لو من 1 إلى أقل من 1000 => 98.25
    - لو أقل من 1 => 0.012345
    """
    if p is None or math.isnan(p):
        return "غير متاح"
    try:
        if p >= 1000:
            s = f"{p:,.0f}"           # 98,000
            s = s.replace(",", ".")   # 98.000
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
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logging.error(f"Error sending message: {e}")


# ==========================
# جلب البيانات من البورصات
# ==========================

def get_binance_klines(symbol: str, limit: int = 120):
    """
    يجلب بيانات شموع يومية من باينانس.
    """
    url = f"{BINANCE_API}/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": "1d",
        "limit": limit,
    }
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
    """
    سعر آخر صفقة من KuCoin (للـ VAI).
    """
    url = f"{KUCOIN_API}/api/v1/market/orderbook/level1"
    params = {"symbol": symbol}
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        raise ValueError(f"KuCoin error: {r.text}")
    j = r.json()
    if j.get("code") != "200000":
        raise ValueError(f"KuCoin bad response: {j}")
    price_str = j["data"]["price"]
    return float(price_str)


# ==========================
# مؤشرات فنية بسيطة
# ==========================

def ema(values, period: int):
    """
    حساب المتوسط المتحرك الأسي EMA.
    """
    if len(values) < period:
        return None

    k = 2 / (period + 1)
    ema_val = sum(values[:period]) / period
    for price in values[period:]:
        ema_val = price * k + ema_val * (1 - k)
    return ema_val


def rsi(values, period: int = 14):
    """
    حساب مؤشر القوة النسبية RSI.
    """
    if len(values) <= period:
        return None

    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = values[i] - values[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-diff)

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi_val = 100 - (100 / (1 + rs))
    return rsi_val


def detect_price_structure(closes):
    """
    رصد شكل حركة السعر التقريبية:
    - اتجاه صاعد
    - اتجاه هابط
    - نطاق عرضي
    - قناة سعرية محتملة
    """
    if len(closes) < 30:
        return "لا توجد بيانات كافية لرصد نموذج سعري واضح حتى الآن."

    recent = closes[-30:]
    start = recent[0]
    end = recent[-1]
    change_pct = (end - start) / start * 100 if start != 0 else 0

    high = max(recent)
    low = min(recent)
    range_pct = (high - low) / low * 100 if low != 0 else 0

    # منطق بسيط لتوصيف الحركة
    if abs(change_pct) < 3 and range_pct < 8:
        return "السعر يتحرك في نطاق عرضي ضيق نسبيًا، مع تذبذب محدود خلال الفترة الأخيرة."
    elif change_pct > 3 and range_pct < 15:
        return "السعر يتحرك في مسار صاعد معتدل، مع قمم وقيعان أعلى بشكل تدريجي."
    elif change_pct < -3 and range_pct < 15:
        return "السعر يتحرك في مسار هابط معتدل، مع قمم وقيعان أدنى بشكل تدريجي."
    elif range_pct >= 15 and change_pct > 0:
        return "السعر في قناة سعرية صاعدة واسعة نسبيًا، ما يعكس موجة تذبذب صاعدة خلال الفترة الماضية."
    elif range_pct >= 15 and change_pct < 0:
        return "السعر في قناة سعرية هابطة واسعة نسبيًا، مع ضغوط بيعية متكررة على الحركة."
    else:
        return "هناك حركة سعرية متذبذبة بدون نموذج واضح تمامًا، ويُفضَّل انتظار مزيد من التأكيد."


# ==========================
# بناء نص التحليل للعملة
# ==========================

def build_analysis_text(symbol_display: str, candles=None, last_price: float = None, is_vai: bool = False) -> str:
    """
    يبني رسالة تحليل احترافية باللغة العربية.
    """
    if is_vai:
        # تحليل مبسط لـ VAI بسبب محدودية البيانات
        price_txt = fmt_price(last_price) if last_price is not None else "غير متاح"
        return (
            f"📊 *تحليل مبسط لعملة* `{symbol_display}`\n\n"
            f"💰 *السعر الحالي:* `{price_txt} USDT`\n\n"
            "🔎 حاليًا يتم جلب السعر من *KuCoin* مع توفر بيانات تاريخية محدودة، لذلك:\n"
            "- تم تقديم قراءة سعرية مبسّطة دون تحليل عميق للاتجاهات.\n"
            "- يُنصح بالاعتماد على إدارة مخاطر حذرة في التداول على هذه العملة.\n\n"
            "🤖 *ملاحظة من نظام الذكاء الاصطناعي:*\n"
            "هذه العملة ذات سيولة وبيانات تاريخية أقل من العملات الرئيسية، لذلك قد تكون الحركة أكثر حدة "
            "ويُفضَّل حجم مخاطرة أقل في حالة التداول عليها."
        )

    if not candles or len(candles) < 20:
        price_txt = fmt_price(last_price) if last_price is not None else "غير متاح"
        return (
            f"📊 *تحليل العملة* `{symbol_display}`\n\n"
            f"💰 *السعر الحالي:* `{price_txt} USDT`\n\n"
            "لا توجد بيانات كافية لبناء تحليل فني موثوق على الإطار اليومي في الوقت الحالي.\n"
            "يُنصح بالانتظار قليلًا حتى تتكوّن حركة سعرية أوضح قبل اتخاذ قرارات تداول.\n\n"
            "🤖 *ملاحظة من نظام الذكاء الاصطناعي:*\n"
            "عند ضعف البيانات التاريخية، يكون الاعتماد على التحليل الفني أقل دقة، لذلك الأفضل التركيز "
            "على إدارة رأس المال وتقليل حجم المخاطرة."
        )

    closes = [c["close"] for c in candles]
    last_candle = candles[-1]
    prev_candle = candles[-2]

    last_close = last_candle["close"]
    prev_close = prev_candle["close"]

    change_pct = (last_close - prev_close) / prev_close * 100 if prev_close != 0 else 0

    # دعم ومقاومة بسيطة من آخر 30 شمعة
    recent = candles[-30:]
    recent_highs = [c["high"] for c in recent]
    recent_lows = [c["low"] for c in recent]
    support = min(recent_lows)
    resistance = max(recent_highs)

    # EMA على الإطار اليومي
    ema_fast = ema(closes, 9)
    ema_slow = ema(closes, 21)

    # RSI
    rsi_val = rsi(closes, 14)

    # اتجاه عام + هيكل سعر
    structure_text = detect_price_structure(closes)

    # توصيف الاتجاه من EMA
    if ema_fast and ema_slow:
        if ema_fast > ema_slow and last_close > ema_fast:
            trend_text = "الاتجاه العام يميل إلى الصعود، مع حفاظ السعر حاليًا على تداولات أعلى من متوسطاته المتوسطة."
        elif ema_fast < ema_slow and last_close < ema_slow:
            trend_text = "الاتجاه العام يميل إلى الهبوط، مع بقاء السعر أسفل المتوسطات المتحركة الرئيسية."
        else:
            trend_text = "الاتجاه العام حيادي نسبيًا، مع تذبذب السعر بالقرب من المتوسطات المتحركة اليومية."
    else:
        trend_text = "لا توجد بيانات كافية لتحديد اتجاه عام واضح من خلال المتوسطات المتحركة."

    # توصيف RSI
    if rsi_val is None:
        rsi_text = "مؤشر القوة النسبية (RSI) غير متاح بشكل موثوق على هذا الرمز حاليًا."
    elif rsi_val > 70:
        rsi_text = f"مؤشر القوة النسبية عند حوالي `{rsi_val:.1f}` → المنطقة أقرب إلى تشبّع شرائي؛ قد تزداد احتمالات التصحيح."
    elif rsi_val < 30:
        rsi_text = f"مؤشر القوة النسبية عند حوالي `{rsi_val:.1f}` → المنطقة أقرب إلى تشبّع بيعي؛ قد تظهر فرص ارتداد محتملة."
    else:
        rsi_text = f"مؤشر القوة النسبية عند حوالي `{rsi_val:.1f}` → حيادي نسبيًا بدون تشبّع واضح في الشراء أو البيع."

    # تلخيص حركة اليوم
    if change_pct > 0.8:
        day_move = "اليوم يميل إلى الإيجابية مع صعود ملحوظ في السعر."
    elif change_pct < -0.8:
        day_move = "اليوم يميل إلى السلبية مع هبوط واضح في السعر."
    else:
        day_move = "تحركات اليوم حتى الآن محدودة وغير حاسمة بشكل كبير."

    price_txt = fmt_price(last_close)
    support_txt = fmt_price(support)
    resistance_txt = fmt_price(resistance)

    # نص نهائي
    text = (
        f"📊 *تحليل فني يومي للعملة* `{symbol_display}`\n\n"
        f"💰 *السعر الحالي:* `{price_txt} USDT`\n"
        f"📈 *تغيّر اليوم:* `{change_pct:.2f}%`\n\n"
        f"🧭 *حركة السعر العامة:*\n"
        f"- {day_move}\n"
        f"- {structure_text}\n\n"
        f"📍 *مستويات فنية مهمة:*\n"
        f"- أقرب دعم يومي تقريبي حول: `{support_txt} USDT`\n"
        f"- أقرب مقاومة يومية تقريبية حول: `{resistance_txt} USDT`\n\n"
        f"📊 *صورة الاتجاه والمتوسطات المتحركة:*\n"
        f"- {trend_text}\n\n"
        f"📉 *وضع مؤشر القوة النسبية (RSI):*\n"
        f"- {rsi_text}\n\n"
        f"🤖 *ملاحظة من نظام الذكاء الاصطناعي للبوت:*\n"
        "هذا التحليل مبني على بيانات يومية وأساليب فنية مبسّطة، ولا يُعتبَر توصية مباشرة بالشراء أو البيع، "
        "بل أداة مساعدة لرؤية أوضح لحالة السوق. يُنصح دائمًا بدمج التحليل الفني مع إدارة مخاطر منضبطة."
    )

    return text


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
        chat_id = message["chat"]["id"]
        text = message.get("text", "").strip()

        # /start
        if text.startswith("/start"):
            welcome = (
                "👋 أهلاً بك في بوت *تحليل الكريبتو اليومي*.\n\n"
                "اكتب الأمر بالشكل التالي لتحليل أي عملة على إطار يومي:\n"
                "`/coin btcusdt`\n"
                "أو ببساطة:\n"
                "`/btc`\n\n"
                "سيقوم البوت بجلب بيانات العملة من باينانس (أو KuCoin في حالة VAI) "
                "ثم يعرض لك ملخصًا فنيًا احترافيًا مدعومًا ببعض آليات الذكاء الاصطناعي. 🤖"
            )
            send_message(chat_id, welcome)
            return "OK", 200

        # أوامر التحليل: /coin أو /btc الخ...
        if text.startswith("/"):
            parts = text[1:].split()
            if not parts:
                send_message(chat_id, "❗ من فضلك اكتب الرمز بعد الأمر، مثل: `/coin btcusdt` أو `/btc`.")
                return "OK", 200

            cmd = parts[0].lower()

            # لو كان الأمر نفسه هو الرمز /btc
            if cmd == "coin":
                if len(parts) < 2:
                    send_message(chat_id, "❗ من فضلك اكتب الرمز بعد الأمر، مثل: `/coin btcusdt`.")
                    return "OK", 200
                user_symbol = parts[1]
            else:
                # اعتبر الأمر نفسه هو الرمز (مثل /btc أو /ethusdt)
                user_symbol = cmd

            # تجهيز الرمز
            user_symbol_clean = user_symbol.replace("/", "").replace(" ", "").upper()
            if not user_symbol_clean.endswith("USDT"):
                user_symbol_clean = user_symbol_clean.replace("USDT", "")  # لو كتبها جوه الرمز
                user_symbol_clean = user_symbol_clean + "USDT"

            symbol_display = user_symbol_clean

            try:
                # حالة VAI من KuCoin
                if user_symbol_clean in ("VAIUSDT", "VAI-USDT"):
                    last_price = get_kucoin_last_price("VAI-USDT")
                    text_reply = build_analysis_text(symbol_display, candles=None, last_price=last_price, is_vai=True)
                    send_message(chat_id, text_reply)
                    return "OK", 200

                # باقي العملات من باينانس
                candles = get_binance_klines(user_symbol_clean, limit=120)
                last_close = candles[-1]["close"] if candles else None
                text_reply = build_analysis_text(symbol_display, candles=candles, last_price=last_close, is_vai=False)
                send_message(chat_id, text_reply)
                return "OK", 200

            except Exception as e:
                logging.error(f"Error in analysis: {e}")
                send_message(
                    chat_id,
                    "⚠️ تعذّر جلب بيانات هذه العملة في الوقت الحالي.\n"
                    "تأكّد من كتابة الرمز بشكل صحيح مثل: `btcusdt` أو جرّب لاحقًا."
                )
                return "OK", 200

        # أي رسالة أخرى
        send_message(
            chat_id,
            "ℹ️ لاستخدام البوت، اكتب مثلاً:\n"
            "`/coin btcusdt`\n"
            "أو:\n`/btc`"
        )
        return "OK", 200

    except Exception as e:
        logging.error(f"Unhandled error in webhook: {e}")
        return "OK", 200


# ==========================
# ضبط الويبهوك وتشغيل السيرفر
# ==========================

def setup_webhook():
    """
    ضبط الويبهوك تلقائيًا مع عنوان Koyeb.
    """
    url = f"{TELEGRAM_API_URL}/setWebhook"
    webhook_url = APP_BASE_URL.rstrip("/") + "/webhook"
    try:
        r = requests.get(url, params={"url": webhook_url}, timeout=10)
        logging.info(f"SetWebhook response: {r.status_code} - {r.text}")
    except Exception as e:
        logging.error(f"Error setting webhook: {e}")


if __name__ == "__main__":
    logging.info("Bot is starting...")
    setup_webhook()
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
