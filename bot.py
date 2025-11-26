
import os
import math
import time
import threading
from datetime import datetime

import logging
import requests
from flask import Flask, request, jsonify

# ==============================
#        الإعدادات العامة
# ==============================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
APP_BASE_URL = (os.getenv("APP_BASE_URL") or "").rstrip("/")

if not TELEGRAM_TOKEN:
    raise RuntimeError("البيئة لا تحتوى على TELEGRAM_TOKEN")

if not APP_BASE_URL:
    raise RuntimeError("البيئة لا تحتوى على APP_BASE_URL")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# صاحب البوت اللى هيوصل له تحذير البيتكوين التلقائى
OWNER_CHAT_ID = 669209875

# متغيرات خاصة بتنبيه BTC التلقائى
LAST_BTC_ALERT_STATE = None   # "normal" / "warning"
LAST_BTC_ALERT_TS = 0         # آخر وقت تم إرسال تحذير فيه
BTC_ALERT_COOLDOWN = 60 * 60  # ساعة بين كل تحذير وتحذير

# إعداد اللوج
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Flask
app = Flask(__name__)


# ==============================
#  دوال مساعدة عامة
# ==============================

def send_message(chat_id: int, text: str, parse_mode: str = "HTML"):
    """إرسال رسالة عادية لتليجرام."""
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            logger.warning("Telegram sendMessage error: %s - %s", r.status_code, r.text)
    except Exception as e:
        logger.exception("Exception while sending message: %s", e)


def fmt_price_human(p: float) -> str:
    """تنسيق رقم بشكل مقروء: 90600 → 90,600 | 0.98765 → 0.99"""
    try:
        if p >= 1000:
            return f"{p:,.0f}"
        elif p >= 1:
            return f"{p:.2f}"
        else:
            return f"{p:.4f}"
    except Exception:
        return str(p)


# ==============================
#   تجهيز رمز العملة + المنصات
# ==============================

def normalize_symbol(user_symbol: str):
    """
    يرجّع:
    - base: اسم العملة بدون USDT
    - binance_symbol: للـ Binance مثل BTCUSDT
    - kucoin_symbol: للـ KuCoin مثل BTC-USDT
    """
    base = user_symbol.strip().upper()
    base = base.replace("USDT", "").replace("-", "").strip()
    if not base:
        return None, None, None

    binance_symbol = base + "USDT"       # مثال: BTC → BTCUSDT
    kucoin_symbol = base + "-USDT"       # مثال: BTC → BTC-USDT

    return base, binance_symbol, kucoin_symbol


# ==============================
#   جلب البيانات من Binance / KuCoin
# ==============================

def fetch_from_binance(symbol: str):
    """
    يحاول يجلب بيانات من Binance.
    يرجّع dict قياسية أو None.
    """
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr"
        r = requests.get(url, params={"symbol": symbol}, timeout=10)
        if r.status_code != 200:
            logger.info("Binance error %s for %s: %s", r.status_code, symbol, r.text)
            return None

        data = r.json()
        price = float(data["lastPrice"])
        change_pct = float(data["priceChangePercent"])
        high = float(data.get("highPrice", price))
        low = float(data.get("lowPrice", price))
        volume = float(data.get("volume", 0))

        return {
            "exchange": "binance",
            "symbol": symbol,
            "price": price,
            "change_pct": change_pct,
            "high": high,
            "low": low,
            "volume": volume,
        }
    except Exception as e:
        logger.exception("Error fetching from Binance: %s", e)
        return None


def fetch_from_kucoin(symbol: str):
    """
    يحاول يجلب بيانات من KuCoin.
    symbol بشكل BTC-USDT.
    """
    try:
        url = "https://api.kucoin.com/api/v1/market/stats"
        r = requests.get(url, params={"symbol": symbol}, timeout=10)
        if r.status_code != 200:
            logger.info("KuCoin error %s for %s: %s", r.status_code, symbol, r.text)
            return None

        payload = r.json()
        if payload.get("code") != "200000":
            logger.info("KuCoin non-success code: %s", payload)
            return None

        data = payload.get("data") or {}
        # last: آخر سعر, changeRate: نسبة التغير (0.0123 يعنى 1.23%)
        price = float(data.get("last") or 0)
        change_rate = float(data.get("changeRate") or 0.0)
        change_pct = change_rate * 100.0
        high = float(data.get("high") or price)
        low = float(data.get("low") or price)
        volume = float(data.get("vol") or 0)

        return {
            "exchange": "kucoin",
            "symbol": symbol,
            "price": price,
            "change_pct": change_pct,
            "high": high,
            "low": low,
            "volume": volume,
        }
    except Exception as e:
        logger.exception("Error fetching from KuCoin: %s", e)
        return None


def fetch_price_data(user_symbol: str):
    """
    يحاول يجلب بيانات السعر:
    1) من Binance
    2) لو فشلت أو الرمز مش موجود → من KuCoin
    يرجع dict موحدة أو None.
    """
    base, binance_symbol, kucoin_symbol = normalize_symbol(user_symbol)
    if not base:
        return None

    # جرّب Binance أولاً
    data = fetch_from_binance(binance_symbol)
    if data:
        return data

    # لو ما نجحش، جرّب KuCoin (زى VAI)
    data = fetch_from_kucoin(kucoin_symbol)
    if data:
        return data

    return None


# ==============================
#     صياغة رسالة التحليل للأوامر /btc /vai /coin
# ==============================

def format_analysis(user_symbol: str) -> str:
    """
    يرجّع نص التحليل النهائى لإرساله لتليجرام.
    فيه دعم VAI من KuCoin تلقائياً.
    """
    data = fetch_price_data(user_symbol)
    if not data:
        # لو فشلنا فى Binance و KuCoin
        return (
            "⚠️ لا يمكن جلب بيانات هذه العملة الآن.\n"
            "تأكد من الرمز (مثال: <code>BTC</code> أو <code>BTCUSDT</code> أو <code>VAI</code>) "
            "وحاول مرة أخرى.\n\n"
            "🤖 <b>ملاحظة الذكاء الاصطناعى:</b>\n"
            "أحيانًا يكون السبب مشكلة مؤقتة فى مزود البيانات أو أن العملة ذات سيولة ضعيفة، "
            "لذلك يُفضّل التحقق من المنصة مباشرة عند الشك."
        )

    price = data["price"]
    change = data["change_pct"]
    high = data["high"]
    low = data["low"]
    exchange = data["exchange"]  # binance / kucoin

    base, binance_symbol, kucoin_symbol = normalize_symbol(user_symbol)
    display_symbol = (binance_symbol if exchange == "binance" else kucoin_symbol).replace("-", "")

    # مستويات دعم / مقاومة بسيطة (تجريبية)
    support = round(low * 0.99, 6) if low > 0 else round(price * 0.95, 6)
    resistance = round(high * 1.01, 6) if high > 0 else round(price * 1.05, 6)

    # RSI تجريبى مبنى على نسبة التغير (مش RSI حقيقى لكنه يعطى إحساس بالزخم)
    rsi_raw = 50 + (change * 0.8)
    rsi = max(0, min(100, rsi_raw))
    if rsi >= 70:
        rsi_trend = "⬆️ مرتفع (تشبّع شرائى محتمل)"
    elif rsi <= 30:
        rsi_trend = "⬇️ منخفض (تشبّع بيع محتمل)"
    else:
        rsi_trend = "🔁 حيادى نسبياً"

    # الاتجاه العام وفقاً لنسبة التغير
    if change > 2:
        trend_text = "الاتجاه العام يميل إلى الصعود مع زخم إيجابى ملحوظ."
    elif change > 0:
        trend_text = "الاتجاه العام يميل إلى الصعود بشكل هادئ."
    elif change > -2:
        trend_text = "الاتجاه العام يميل إلى الهبوط الخفيف مع بعض التذبذب."
    else:
        trend_text = "الاتجاه العام يميل إلى الهبوط مع ضغوط بيعية واضحة."

    # ملاحظة خاصة لو KuCoin (زى حالة VAI)
    if exchange == "kucoin":
        source_note = (
            "⚙️ <b>مصدر البيانات:</b> KuCoin\n"
            "- السعر يتم جلبه من KuCoin مع توفر بيانات تاريخية محدودة نسبيًا.\n"
            "- لذلك التحليل يكون <b>مبسّط ومحافظ</b>، "
            "ويُفضّل استخدام إدارة مخاطر منخفضة.\n\n"
        )
    else:
        source_note = (
            "⚙️ <b>مصدر البيانات:</b> Binance\n"
            "- التحليل يعتمد على بيانات يومية ومؤشرات فنية مبسطة.\n\n"
        )

    ai_note = (
        "🤖 <b>ملاحظة الذكاء الاصطناعى:</b>\n"
        "هذا التحليل يساعدك على فهم الاتجاه وحركة السعر، "
        "وليس توصية مباشرة بالشراء أو البيع.\n"
        "يُفضّل دائمًا دمج التحليل الفنى مع خطة إدارة مخاطر منضبطة.\n"
    )

    msg = f"""
📊 <b>تحليل فنى يومى للعملة {display_symbol}</b>

💰 <b>السعر الحالى:</b> {price:.6f}
📉 <b>تغير اليوم:</b> %{change:.2f}

🎯 <b>حركة السعر العامة:</b>
- {trend_text}

📍 <b>مستويات فنية مهمة:</b>
- دعم يومى تقريبى حول: <b>{support}</b>
- مقاومة يومية تقريبية حول: <b>{resistance}</b>

📊 <b>صورة الاتجاه والمتوسطات:</b>
- قراءة مبسطة بناءً على الحركة اليومية وبعض المستويات الفنية.

📉 <b>RSI:</b>
- مؤشر القوة النسبية عند حوالى: <b>{rsi:.1f}</b> → {rsi_trend}

{source_note}{ai_note}
""".strip()

    return msg


# ==============================
#   مؤشرات فنية خاصة بتقرير BTC
# ==============================

def get_binance_klines(symbol: str, limit: int = 120):
    """
    جلب شموع يومية من Binance لاستخدامها فى تقرير BTC المتقدم.
    """
    try:
        url = "https://api.binance.com/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": "1d",
            "limit": limit,
        }
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            logger.info("Binance klines error %s for %s: %s", r.status_code, symbol, r.text)
            return None

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
    except Exception as e:
        logger.exception("Error fetching klines: %s", e)
        return None


def ema(values, period: int):
    """حساب المتوسط المتحرك الأسي EMA."""
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema_val = sum(values[:period]) / period
    for price in values[period:]:
        ema_val = price * k + ema_val * (1 - k)
    return ema_val


def rsi(values, period: int = 14):
    """حساب مؤشر القوة النسبية RSI."""
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


# ==============================
#   تقرير + تحذير ذكى للبيتكوين BTC
# ==============================

def build_btc_ai_report(candles, danger: bool = False) -> str:
    """
    تقرير شامل للبيتكوين بنفس روح الرسالة التى أرسلتها:
    - تصحيح تاريخ التحليل
    - نظرة عامة
    - مؤشرات فنية
    - تقييم الوضع
    - التوقعات
    - الملخص النهائى
    - رسالة اليوم من IN CRYPTO Ai
    """
    closes = [c["close"] for c in candles]
    last_candle = candles[-1]
    prev_candle = candles[-2]

    last_close = last_candle["close"]
    prev_close = prev_candle["close"]

    change_pct = (last_close - prev_close) / prev_close * 100 if prev_close != 0 else 0

    highs = [c["high"] for c in candles[-30:]]
    lows = [c["low"] for c in candles[-30:]]
    recent_high = max(highs)
    recent_low = min(lows)

    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    rsi_val = rsi(closes, 14)

    price_txt = fmt_price_human(last_close)
    recent_high_txt = fmt_price_human(recent_high)
    recent_low_txt = fmt_price_human(recent_low)

    # تقريب لمستويات أشبه بـ 96,000 / 98,000 / 102,000
    rounded = round(last_close / 1000) * 1000
    level1 = rounded - 2000
    level2 = rounded - 1000
    level3 = rounded + 1000
    level4 = rounded + 3000

    level1_txt = fmt_price_human(level1)
    level2_txt = fmt_price_human(level2)
    level3_txt = fmt_price_human(level3)
    level4_txt = fmt_price_human(level4)

    # توصيف RSI
    if rsi_val is None:
        rsi_desc = "RSI غير متاح بشكل واضح حاليًا."
    elif rsi_val < 30:
        rsi_desc = f"RSI عند حوالى {rsi_val:.1f} → يشير إلى تشبّع بيعى واضح، يعكس ضغطًا بيعيًا قويًا."
    elif rsi_val > 70:
        rsi_desc = f"RSI عند حوالى {rsi_val:.1f} → يشير إلى تشبّع شرائى وقد يزيد احتمال حدوث جنى أرباح."
    else:
        rsi_desc = f"RSI عند حوالى {rsi_val:.1f} → حالة حيادية نسبيًا بدون تشبّع واضح."

    # توصيف الاتجاه من EMA
    if ema50 and ema200:
        if last_close < ema50 < ema200:
            trend_desc = (
                "الاتجاه قصير المدى يميل للسلبية مع تداول السعر أسفل متوسط 50 يوم "
                "وقريب من متوسط 200 يوم."
            )
        elif last_close < ema200:
            trend_desc = "السعر أسفل متوسط 200 يوم، ما يعكس ضغوط هابطة متوسطة إلى طويلة المدى."
        elif last_close > ema50 > ema200:
            trend_desc = "الاتجاه العام يميل إلى الإيجابية مع تمركز السعر أعلى المتوسطات الرئيسية."
        else:
            trend_desc = "السعر يتذبذب بالقرب من المتوسطات المتحركة، ما يعكس حالة حيادية نسبية."
    else:
        trend_desc = "لا توجد بيانات كافية لحساب متوسطات 50 و 200 يوم بشكل موثوق."

    # توصيف حجم الحركة اليومية
    if change_pct <= -5:
        day_move_desc = f"اليوم يشهد هبوطًا قويًا بحوالى %{change_pct:.2f} مقارنة بإغلاق الأمس."
    elif change_pct >= 5:
        day_move_desc = f"اليوم يشهد صعودًا قويًا بحوالى %{change_pct:.2f} مقارنة بإغلاق الأمس."
    elif change_pct < -1:
        day_move_desc = f"اليوم يميل للهبوط بحوالى %{change_pct:.2f}."
    elif change_pct > 1:
        day_move_desc = f"اليوم يميل للصعود بحوالى %{change_pct:.2f}."
    else:
        day_move_desc = f"تغيّر اليوم محدود عند حوالى %{change_pct:.2f}."

    today_str = datetime.utcnow().strftime("%A %d %B %Y")  # تاريخ نصى انجليزى، ممكن نسيبه كده

    # نص "رسالة اليوم" مختلف لو danger أو لا
    if danger:
        ai_tail = (
            "⚠️ رسالة اليوم من IN CRYPTO Ai:\n\n"
            "> السوق يظهر حاليًا إشارات ضغط بيعى أو حركة هابطة قوية.\n"
            "فى مثل هذه الأجواء، يكون الصبر وتقليل المخاطرة أهم من مطاردة كل حركة.\n"
            "تأجيل قرارات التداول المندفعة، والالتزام بخطط وقف الخسارة، يساعد على حماية رأس المال والأرباح السابقة.\n"
            "IN CRYPTO Ai 🤖"
        )
    else:
        ai_tail = (
            "⚠️ رسالة اليوم من IN CRYPTO Ai:\n\n"
            "> التعامل مع البيتكوين يحتاج دائمًا إلى صبر وانضباط.\n"
            "اختيار الفرص الواضحة أفضل بكثير من محاولة دخول كل موجة صغيرة.\n"
            "حافظ على خطتك وإدارة المخاطر، ودع السوق يعمل لصالحك على المدى الأطول.\n"
            "IN CRYPTO Ai 🤖"
        )

    text = f"""
تصحيح تاريخ التحليل ✅

🧭 تحليل الذكاء الاصطناعي لسوق البيتكوين – {today_str}

🏦 السوق حاليًا يتحرك ضمن نطاق قصير المدى مع تركيز أساسى حول مستويات نفسية مهمة.
السعر الحالي للبيتكوين يدور حول ${price_txt}.
{day_move_desc}
يتداول السعر خلال الفترة الأخيرة بين قاع تقريبى عند ${recent_low_txt} وقمّة قريبة من ${recent_high_txt}.

---
📊 المؤشرات الفنية:

- {rsi_desc}
- {trend_desc}
- النطاق السعري الأخير يعكس توازناً نسبياً بين المشترين والبائعين بين ${recent_low_txt} و ${recent_high_txt}.

---
💎 تقييم الوضع العام:

استثماريًا:
- التماسك أعلى المنطقة ${level1_txt}–${level2_txt} يُعتبَر إشارة أولية لتحسن قصير المدى.
- الإغلاق المستمر أعلى ${level3_txt} يفتح المجال لتحرك صعودى أوسع نحو مناطق أقرب من ${level4_txt} وما فوق.

مضاربيًا:
- فى حال زيادة التذبذب أو ظهور شموع هابطة قوية، يُفضَّل تقليل حجم المراكز وخاصة ذات الرافعة المالية العالية.
- التركيز يكون على احترام نقاط الخروج وعدم ملاحقة الحركة العنيفة.

---
⚙️ التوقعات القادمة (وفق البيانات الحالية):

- التماسك أعلى ${level2_txt} يعزّز فرص الاستقرار ومحاولات الصعود التدريجى.
- كسر واضح ومتكرر أسفل القاع الأخير قرب ${recent_low_txt} قد يفتح المجال لتصحيح أعمق على المدى القصير.

---
📌 الملخص النهائي:

> السوق على المدى القصير ما زال حساسًا لحركة السيولة، مع مزيج بين ضغط بيعى وفترات ارتداد.
التركيز حاليًا على مراقبة المناطق ${level1_txt}–${level2_txt} كمناطق دعم، و${level3_txt} كمستوى مقاومة رئيسى.
الالتزام بالانضباط وعدم الإفراط فى المخاطرة يظل هو العامل الأهم.

---
{ai_tail}
""".strip()

    return text


def analyze_btc_for_alert(candles):
    """
    يقرر هل يتم إرسال تنبيه خاص بالبيتكوين الآن أم لا.
    يرجع (should_alert, report_text)
    """
    closes = [c["close"] for c in candles]
    last_candle = candles[-1]
    prev_candle = candles[-2]

    last_close = last_candle["close"]
    prev_close = prev_candle["close"]

    change_pct = (last_close - prev_close) / prev_close * 100 if prev_close != 0 else 0
    rsi_val = rsi(closes, 14)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    danger = False

    # شروط بسيطة للخطر:
    # 1) RSI أقل من 30 وهبوط يومى أقوى من -2%
    if rsi_val is not None and rsi_val < 30 and change_pct < -2:
        danger = True
    # 2) هبوط يومى حاد أقل من -5%
    elif change_pct <= -5:
        danger = True
    # 3) كسر سلبى أسفل المتوسطات مع هبوط واضح
    elif ema50 and ema200 and last_close < ema50 < ema200 and change_pct < -2:
        danger = True

    if not danger:
        return False, None

    report_text = build_btc_ai_report(candles, danger=True)
    return True, report_text


def btc_monitor_loop():
    """
    حلقة مراقبة البيتكوين فى الخلفية.
    بتشتغل كل 30 دقيقة وتبعت تقرير+تحذير لو لقت شروط خطر.
    """
    global LAST_BTC_ALERT_STATE, LAST_BTC_ALERT_TS

    while True:
        try:
            logger.info("BTC monitor: checking market...")
            candles = get_binance_klines("BTCUSDT", limit=200)
            if not candles or len(candles) < 60:
                logger.info("BTC monitor: not enough data for BTC.")
            else:
                should_alert, text = analyze_btc_for_alert(candles)
                now_ts = time.time()

                if should_alert and text:
                    # نطبق كول داون: مايبعتش كل شوية
                    if LAST_BTC_ALERT_STATE != "warning" or (now_ts - LAST_BTC_ALERT_TS) > BTC_ALERT_COOLDOWN:
                        logger.info("BTC monitor: sending alert to owner...")
                        send_message(OWNER_CHAT_ID, text)
                        LAST_BTC_ALERT_STATE = "warning"
                        LAST_BTC_ALERT_TS = now_ts
                    else:
                        logger.info("BTC monitor: warning detected but still in cooldown.")
                else:
                    LAST_BTC_ALERT_STATE = "normal"

        except Exception as e:
            logger.exception("BTC monitor error: %s", e)

        # كل 30 دقيقة
        time.sleep(1800)


def start_btc_monitor_thread():
    t = threading.Thread(target=btc_monitor_loop, daemon=True)
    t.start()
    logger.info("BTC monitor thread started.")


# ==============================
#          مسارات Flask
# ==============================

@app.route("/", methods=["GET"])
def index():
    return "Crypto ideas bot is running.", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(force=True, silent=True) or {}
    logger.info("Update: %s", update)

    if "message" not in update:
        return jsonify(ok=True)

    msg = update["message"]
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    lower_text = text.lower()

    # /start
    if lower_text == "/start":
        welcome = (
            "👋 أهلاً بك فى بوت <b>IN CRYPTO Ai</b>.\n\n"
            "يمكنك طلب تحليل فنى لأى عملة:\n"
            "➤ <code>/btc</code>\n"
            "➤ <code>/vai</code>\n"
            "➤ <code>/coin btc</code>\n"
            "➤ <code>/coin btcusdt</code>\n"
            "➤ <code>/coin vai</code> أو أى رمز آخر.\n\n"
            "البوت يحاول أولاً جلب البيانات من Binance، "
            "وإذا لم يجد العملة يحاول تلقائيًا من KuCoin.\n\n"
            "🔔 بالإضافة لذلك، يقوم البوت بمراقبة البيتكوين على الإطار اليومى، "
            "وعند ظهور ظروف خطرة يرسل لك تقريرًا وتحذيرًا تلقائيًا."
        )
        send_message(chat_id, welcome)
        return jsonify(ok=True)

    # أمر اختبار تقرير وتحذير BTC يدويًا
    if lower_text in ("/btc_report", "/btcreport"):
        try:
            candles = get_binance_klines("BTCUSDT", limit=200)
            if not candles or len(candles) < 60:
                send_message(chat_id, "⚠️ لا توجد بيانات كافية الآن لإنشاء تقرير مفصل للبيتكوين.")
            else:
                # هنا danger=False لأن ده تقرير اختبار/يدوى، مش تنبيه خطر تلقائى
                report = build_btc_ai_report(candles, danger=False)
                send_message(chat_id, report)
        except Exception as e:
            logger.exception("Error building BTC report: %s", e)
            send_message(chat_id, "⚠️ تعذّر إنشاء تقرير البيتكوين الآن، جرّب مرة أخرى لاحقًا.")
        return jsonify(ok=True)

    # /btc (تحليل مختصر من ticker)
    if lower_text == "/btc":
        reply = format_analysis("BTCUSDT")
        send_message(chat_id, reply)
        return jsonify(ok=True)

    # /vai  (هنا VAI → KuCoin تلقائياً لو مش موجودة فى Binance)
    if lower_text == "/vai":
        reply = format_analysis("VAIUSDT")
        send_message(chat_id, reply)
        return jsonify(ok=True)

    # /coin xxx
    if lower_text.startswith("/coin"):
        parts = lower_text.split()
        if len(parts) < 2:
            send_message(
                chat_id,
                "⚠️ استخدم الأمر بهذا الشكل:\n"
                "<code>/coin btc</code>\n"
                "<code>/coin btcusdt</code>\n"
                "<code>/coin vai</code>",
            )
        else:
            user_symbol = parts[1]
            reply = format_analysis(user_symbol)
            send_message(chat_id, reply)
        return jsonify(ok=True)

    # أى رسالة أخرى
    send_message(
        chat_id,
        "⚙️ اكتب /start لعرض الأوامر المتاحة.\n"
        "مثال سريع: <code>/btc</code> أو <code>/coin btc</code>.",
    )
    return jsonify(ok=True)


# ==============================
#       تفعيل الـ Webhook
# ==============================

def setup_webhook():
    """تعيين Webhook عند تشغيل السيرفر."""
    webhook_url = f"{APP_BASE_URL}/webhook"
    try:
        r = requests.get(
            f"{TELEGRAM_API}/setWebhook",
            params={"url": webhook_url},
            timeout=10,
        )
        logger.info("Webhook response: %s - %s", r.status_code, r.text)
    except Exception as e:
        logger.exception("Error setting webhook: %s", e)


if __name__ == "__main__":
    logger.info("Bot is starting...")
    setup_webhook()
    start_btc_monitor_thread()  # تشغيل مراقبة BTC فى الخلفية
    # تشغيل Flask على 8080
    app.run(host="0.0.0.0", port=8080)
