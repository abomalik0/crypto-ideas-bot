import os
import logging
import math
from typing import List, Dict, Optional

import requests
from flask import Flask, request, jsonify

# ==========================
# إعدادات من متغيرات البيئة
# ==========================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
APP_BASE_URL = os.getenv("APP_BASE_URL", "").strip().rstrip("/")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in environment variables.")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

BINANCE_API = "https://api.binance.com"
KUCOIN_API = "https://api.kucoin.com"

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# ==========================
# دوال تنسيق ومساعدة
# ==========================

def fmt_price(p: Optional[float]) -> str:
    """
    تنسيق السعر بشكل احترافي:
    - لو None => "0"
    - لو السعر كبير (>= 1000) => 98.000
    - من 1 إلى أقل من 1000 => 98.25
    - أقل من 1 => 0.012345
    """
    try:
        if p is None or math.isnan(float(p)):
            return "0"

        p = float(p)

        if p >= 1000:
            s = f"{p:,.0f}"          # 98,000
            return s.replace(",", ".")   # 98.000
        elif p >= 1:
            s = f"{p:.2f}".rstrip("0").rstrip(".")
            return s
        else:
            s = f"{p:.6f}".rstrip("0").rstrip(".")
            return s or "0"
    except Exception:
        return "0"


def send_message(chat_id: int, text: str):
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        requests.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json=payload,
            timeout=10,
        )
    except Exception as e:
        logging.error(f"Error sending message: {e}")


# ==========================
# جلب البيانات من البورصات
# ==========================

def get_binance_klines(symbol: str, limit: int = 120) -> List[Dict]:
    """
    شموع يومية من باينانس.
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
        candles.append(
            {
                "open_time": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
            }
        )
    return candles


def get_kucoin_klines(symbol: str = "VAI-USDT", limit: int = 120) -> List[Dict]:
    """
    شموع يومية من KuCoin (تُستخدم لـ VAI).
    KuCoin يعيد الشموع بهذا الشكل:
    [ time, open, close, high, low, volume, turnover ]
    """
    url = f"{KUCOIN_API}/api/v1/market/candles"
    params = {
        "symbol": symbol,
        "type": "1day",
    }
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        raise ValueError(f"KuCoin error: {r.text}")

    j = r.json()
    if j.get("code") != "200000":
        raise ValueError(f"KuCoin bad response: {j}")

    data = j.get("data", [])
    if not data:
        raise ValueError("KuCoin returned no candles.")

    # البيانات بتيجي غالبًا بترتيب تنازلي، نخليها تصاعدي ونقصّ على limit
    sorted_data = sorted(data, key=lambda x: float(x[0]))[-limit:]

    candles = []
    for row in sorted_data:
        # [time, open, close, high, low, volume, turnover]
        t = int(row[0])
        o = float(row[1])
        c = float(row[2])
        h = float(row[3])
        l = float(row[4])
        v = float(row[5])
        candles.append(
            {
                "open_time": t,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
        )
    return candles


# ==========================
# مؤشرات فنية بسيطة
# ==========================

def ema(values: List[float], period: int) -> Optional[float]:
    """
    المتوسط المتحرك الأسي EMA.
    """
    if len(values) < period:
        return None

    k = 2 / (period + 1)
    ema_val = sum(values[:period]) / period
    for price in values[period:]:
        ema_val = price * k + ema_val * (1 - k)
    return ema_val


def rsi(values: List[float], period: int = 14) -> Optional[float]:
    """
    مؤشر القوة النسبية RSI.
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


def detect_price_structure(closes: List[float]) -> str:
    """
    رصد شكل حركة السعر التقريبية:
    - اتجاه صاعد / هابط / نطاق عرضي / قناة سعرية واسعة ... إلخ.
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
# بناء نص التحليل
# ==========================

def build_analysis_text(symbol_display: str, candles: List[Dict]) -> str:
    """
    يبني رسالة تحليل فني يومي بالشكل اللي اتفقنا عليه.
    """
    if not candles or len(candles) < 20:
        last_close = candles[-1]["close"] if candles else 0.0
        price_txt = fmt_price(last_close)
        return (
            f"📊 *تحليل فني يومي للعملة* `{symbol_display}`\n\n"
            f"💰 *السعر الحالي:* `{price_txt}`\n\n"
            "لا توجد بيانات تاريخية كافية على الإطار اليومي لبناء تحليل فني موثوق حاليًا.\n"
            "يُنصح بالانتظار حتى تتكوّن حركة سعرية أوضح قبل اتخاذ قرارات تداول.\n\n"
            "🤖 *ملاحظة الذكاء الاصطناعي:*\n"
            "عند ضعف البيانات التاريخية، يكون الاعتماد على التحليل الفني أقل دقة، "
            "لذلك الأفضل التركيز على إدارة رأس المال وتقليل المخاطرة."
        )

    closes = [c["close"] for c in candles]
    last_candle = candles[-1]
    prev_candle = candles[-2]

    last_close = last_candle["close"]
    prev_close = prev_candle["close"]
    change_pct = (last_close - prev_close) / prev_close * 100 if prev_close != 0 else 0.0

    # دعم / مقاومة من آخر 30 شمعة
    recent = candles[-30:]
    recent_highs = [c["high"] for c in recent]
    recent_lows = [c["low"] for c in recent]
    support = min(recent_lows) if recent_lows else 0.0
    resistance = max(recent_highs) if recent_highs else 0.0

    ema_fast = ema(closes, 9)
    ema_slow = ema(closes, 21)
    rsi_val = rsi(closes, 14)

    # هيكل السعر
    structure_text = detect_price_structure(closes)

    # توصيف الاتجاه العام من EMA
    if ema_fast is not None and ema_slow is not None:
        if ema_fast > ema_slow and last_close > ema_fast:
            trend_text = "الاتجاه العام يميل للصعود، مع تداول السعر أعلى المتوسطات المتحركة الرئيسية."
        elif ema_fast < ema_slow and last_close < ema_slow:
            trend_text = "الاتجاه العام يميل للهبوط، مع بقاء السعر أسفل المتوسطات المتحركة الرئيسية."
        else:
            trend_text = "الاتجاه العام أقرب للحياد، مع تداول السعر بالقرب من المتوسطات المتحركة."
    else:
        trend_text = "لا توجد بيانات كافية لتحديد اتجاه عام واضح من خلال المتوسطات المتحركة."

    # توصيف RSI
    if rsi_val is None:
        rsi_text = "RSI غير متاح بشكل موثوق على هذا الرمز حاليًا."
    elif rsi_val > 70:
        rsi_text = f"مؤشر القوة النسبية عند حوالي `{rsi_val:.1f}` → منطقة قريبة من تشبع شرائي؛ قد تزداد احتمالات التصحيح."
    elif rsi_val < 30:
        rsi_text = f"مؤشر القوة النسبية عند حوالي `{rsi_val:.1f}` → منطقة قريبة من تشبع بيعي؛ قد تظهر فرص ارتداد محتملة."
    else:
        rsi_text = f"مؤشر القوة النسبية عند حوالي `{rsi_val:.1f}` → حيادي نسبيًا بدون تشبع واضح في الشراء أو البيع."

    # تلخيص حركة اليوم
    if change_pct > 0.8:
        day_move = "اليوم يميل للإيجابية مع صعود ملحوظ في السعر."
    elif change_pct < -0.8:
        day_move = "اليوم يميل للسلبية مع هبوط واضح في السعر."
    else:
        day_move = "تحركات اليوم حتى الآن محدودة وغير حاسمة بشكل كبير."

    price_txt = fmt_price(last_close)
    support_txt = fmt_price(support)
    resistance_txt = fmt_price(resistance)

    change_str = f"{change_pct:.2f}%"

    text = (
        f"📊 *تحليل فني يومي للعملة* `{symbol_display}`\n\n"
        f"💰 *السعر الحالي:* `{price_txt}`\n"
        f"📉 *تغيّر اليوم:* `{change_str}`\n\n"
        f"🎯 *حركة السعر العامة:*\n"
        f"- {day_move}\n"
        f"- {structure_text}\n\n"
        f"📍 *مستويات فنية مهمة:*\n"
        f"- دعم يومي تقريبي حول: `{support_txt}`\n"
        f"- مقاومة يومية تقريبية حول: `{resistance_txt}`\n\n"
        f"📊 *صورة الاتجاه والمتوسطات:*\n"
        f"- {trend_text}\n\n"
        f"📏 *RSI:*\n"
        f"- {rsi_text}\n\n"
        "🤖 *ملاحظة الذكاء الاصطناعي:*\n"
        "هذا التحليل يساعد على فهم الاتجاه وحركة السعر، وليس توصية مباشرة بالشراء أو البيع. "
        "يُنصح دائمًا بدمج التحليل الفني مع إدارة مخاطر منضبطة."
    )

    return text


# ==========================
# Webhook + معالجة الأوامر
# ==========================

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ok"})


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

        if not text:
            return "OK", 200

        # /start
        if text.startswith("/start"):
            welcome = (
                "👋 أهلاً بك!\n\n"
                "اكتب `/btc` أو `/coin btcusdt` للحصول على تحليل يومي لأي عملة.\n"
                "مثال:\n"
                "`/coin btcusdt`\n"
                "`/coin eth`\n"
                "`/btc`\n"
                "`/vai`"
            )
            send_message(chat_id, welcome)
            return "OK", 200

        # أوامر تبدأ بـ "/"
        if text.startswith("/"):
            parts = text[1:].split()
            if not parts:
                send_message(
                    chat_id,
                    "❗ من فضلك اكتب الرمز بعد الأمر، مثل: `/coin btcusdt` أو `/btc`.",
                )
                return "OK", 200

            cmd = parts[0].lower()

            if cmd == "coin":
                if len(parts) < 2:
                    send_message(
                        chat_id,
                        "❗ من فضلك اكتب الرمز بعد الأمر، مثل: `/coin btcusdt`.",
                    )
                    return "OK", 200
                user_symbol = parts[1]
            else:
                # الأمر نفسه هو الرمز: /btc, /eth, /vai ...
                user_symbol = cmd

            # تجهيز الرمز
            user_symbol_clean = (
                user_symbol.replace("/", "").replace(" ", "").upper()
            )

            # لو كتب مثلاً btc بدون usdt
            if not user_symbol_clean.endswith("USDT"):
                user_symbol_clean = user_symbol_clean.replace("USDT", "")
                user_symbol_clean = user_symbol_clean + "USDT"

            symbol_display = user_symbol_clean

            try:
                # VAI من KuCoin
                if user_symbol_clean in ("VAIUSDT", "VAI-USDT"):
                    candles = get_kucoin_klines("VAI-USDT", limit=120)
                else:
                    # باقي العملات من باينانس
                    candles = get_binance_klines(user_symbol_clean, limit=120)

                text_reply = build_analysis_text(symbol_display, candles)
                send_message(chat_id, text_reply)
                return "OK", 200

            except Exception as e:
                logging.error(f"Error in analysis: {e}")
                send_message(
                    chat_id,
                    "⚠️ تعذّر جلب بيانات هذه العملة في الوقت الحالي.\n"
                    "تأكّد من كتابة الرمز بشكل صحيح مثل: `btcusdt` أو جرّب لاحقًا.",
                )
                return "OK", 200

        # أي رسالة تانية
        send_message(
            chat_id,
            "ℹ️ لاستخدام البوت، اكتب مثلاً:\n`/btc`\nأو:\n`/coin btcusdt`",
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
    ضبط الويبهوك تلقائيًا باستخدام APP_BASE_URL من كوييب.
    """
    if not APP_BASE_URL:
        logging.warning("APP_BASE_URL is not set; webhook not configured.")
        return

    webhook_url = APP_BASE_URL.rstrip("/") + "/webhook"
    url = f"{TELEGRAM_API_URL}/setWebhook"

    try:
        r = requests.get(url, params={"url": webhook_url}, timeout=10)
        logging.info(f"setWebhook response: {r.status_code} - {r.text}")
    except Exception as e:
        logging.error(f"Error setting webhook: {e}")


if __name__ == "__main__":
    logging.info("Bot is starting...")
    setup_webhook()
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
