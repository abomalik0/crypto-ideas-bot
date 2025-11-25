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
        r = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload, timeout=10)
        if r.status_code != 200:
            logging.error(f"send_message error: {r.status_code} - {r.text}")
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
# بناء نص التحليل للعملة (أمر /coin و /btc إلخ)
# ==========================

def build_analysis_text(symbol_display: str, candles=None, last_price: float = None, is_vai: bool = False) -> str:
    """
    يبني رسالة تحليل احترافية باللغة العربية لأي عملة يطلبها المستخدم.
    """
    if is_vai:
        price_txt = fmt_price(last_price) if last_price is not None else "غير متاح"
        return (
            f"📊 *تحليل مبسط لعملة* `{symbol_display}`\n\n"
            f"💰 *السعر الحالي:* `{price_txt}`\n\n"
            "🔎 السعر يتم جلبه من *KuCoin* مع توفر بيانات تاريخية محدودة، لذلك:\n"
            "- التحليل الفني عميق محدود مقارنةً بالعملات الرئيسية.\n"
            "- يُنصح بإدارة مخاطرة حذرة عند التداول على هذه العملة.\n\n"
            "🤖 *ملاحظة من نظام الذكاء الاصطناعي:*\n"
            "العملات ذات السيولة الأقل غالبًا ما تتحرك بشكل أكثر حدة، لذلك يفضَّل تقليل حجم الصفقات."
        )

    if not candles or len(candles) < 20:
        price_txt = fmt_price(last_price) if last_price is not None else "غير متاح"
        return (
            f"📊 *تحليل العملة* `{symbol_display}`\n\n"
            f"💰 *السعر الحالي:* `{price_txt}`\n\n"
            "لا توجد بيانات كافية لبناء تحليل فني موثوق على الإطار اليومي في الوقت الحالي.\n"
            "يُنصح بالانتظار حتى تتكوّن حركة سعرية أوضح قبل اتخاذ قرارات التداول.\n\n"
            "🤖 *ملاحظة من نظام الذكاء الاصطناعي:*\n"
            "ضعف البيانات التاريخية يقلل من دقة التحليل الفني، لذلك التركيز يكون أكثر على إدارة رأس المال."
        )

    closes = [c["close"] for c in candles]
    last_candle = candles[-1]
    prev_candle = candles[-2]

    last_close = last_candle["close"]
    prev_close = prev_candle["close"]

    change_pct = (last_close - prev_close) / prev_close * 100 if prev_close != 0 else 0

    recent = candles[-30:]
    recent_highs = [c["high"] for c in recent]
    recent_lows = [c["low"] for c in recent]
    support = min(recent_lows)
    resistance = max(recent_highs)

    ema_fast = ema(closes, 9)
    ema_slow = ema(closes, 21)
    rsi_val = rsi(closes, 14)
    structure_text = detect_price_structure(closes)

    # الاتجاه العام من المتوسطات
    if ema_fast and ema_slow:
        if ema_fast > ema_slow and last_close > ema_fast:
            trend_text = "الاتجاه العام يميل إلى الصعود مع تداول السعر أعلى المتوسطات المتحركة المتوسطة."
        elif ema_fast < ema_slow and last_close < ema_slow:
            trend_text = "الاتجاه العام يميل إلى الهبوط مع بقاء السعر أسفل المتوسطات المتحركة الرئيسية."
        else:
            trend_text = "الاتجاه العام حيادي نسبيًا مع تذبذب السعر بالقرب من المتوسطات المتحركة اليومية."
    else:
        trend_text = "لا توجد بيانات كافية لتحديد اتجاه عام واضح من خلال المتوسطات المتحركة."

    # توصيف RSI
    if rsi_val is None:
        rsi_text = "مؤشر القوة النسبية (RSI) غير متاح بشكل موثوق على هذا الرمز حاليًا."
    elif rsi_val > 70:
        rsi_text = f"مؤشر القوة النسبية عند حوالي `{rsi_val:.1f}` → منطقة تشبّع شرائي؛ تزيد احتمالات جني الأرباح أو التصحيح."
    elif rsi_val < 30:
        rsi_text = f"مؤشر القوة النسبية عند حوالي `{rsi_val:.1f}` → منطقة تشبّع بيعي؛ قد تظهر فرص ارتداد لكن مع ضرورة الحذر."
    else:
        rsi_text = f"مؤشر القوة النسبية عند حوالي `{rsi_val:.1f}` → حالة حيادية بدون تشبّع واضح في الشراء أو البيع."

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

    text = (
        f"📊 *تحليل فني يومي للعملة* `{symbol_display}`\n\n"
        f"💰 *السعر الحالي:* `{price_txt}`\n"
        f"📈 *تغيّر اليوم:* `{change_pct:.2f}%`\n\n"
        f"🧭 *حركة السعر العامة:*\n"
        f"- {day_move}\n"
        f"- {structure_text}\n\n"
        f"📍 *مستويات فنية مهمة:*\n"
        f"- أقرب دعم يومي تقريبي حول: `{support_txt}`\n"
        f"- أقرب مقاومة يومية تقريبية حول: `{resistance_txt}`\n\n"
        f"📊 *صورة الاتجاه والمتوسطات المتحركة:*\n"
        f"- {trend_text}\n\n"
        f"📉 *وضع مؤشر القوة النسبية (RSI):*\n"
        f"- {rsi_text}\n\n"
        f"🤖 *ملاحظة من نظام الذكاء الاصطناعي للبوت:*\n"
        "هذا التحليل مبني على بيانات يومية وأساليب فنية مبسّطة، ولا يُعتبَر توصية مباشرة بالشراء أو البيع، "
        "بل أداة مساعدة لرؤية أوضح لحالة السوق مع ضرورة الالتزام بإدارة مخاطر منضبطة."
    )

    return text


# ==========================
# تقرير وتنبيه ذكي للبيتكوين BTC
# ==========================

def build_btc_market_report(candles):
    """
    يبني تقرير شامل + تحذير محتمل للبيتكوين فقط،
    بنفس روح الرسالة الاحترافية التي أعطيتها لكن مبني على البيانات الفعلية.
    """
    closes = [c["close"] for c in candles]
    last_candle = candles[-1]
    prev_candle = candles[-2]

    last_close = last_candle["close"]
    prev_close = prev_candle["close"]

    change_pct = (last_close - prev_close) / prev_close * 100 if prev_close != 0 else 0

    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    rsi_val = rsi(closes, 14)

    recent = candles[-30:]
    highs = [c["high"] for c in recent]
    lows = [c["low"] for c in recent]
    recent_high = max(highs)
    recent_low = min(lows)

    # تقريب لمستويات "نفس فكرة 98000 / 102000" حسب السعر الحالي
    price_rounded_1k = round(last_close / 1000) * 1000
    level_mid1 = price_rounded_1k - 2000   # تقريب لمستوى دعم
    level_mid2 = price_rounded_1k         # مستوى محوري
    level_up = price_rounded_1k + 2000    # مقاومة عليا تقريبية

    price_txt = fmt_price(last_close)
    recent_high_txt = fmt_price(recent_high)
    recent_low_txt = fmt_price(recent_low)
    level_mid1_txt = fmt_price(level_mid1)
    level_mid2_txt = fmt_price(level_mid2)
    level_up_txt = fmt_price(level_up)

    # توصيف RSI
    if rsi_val is None:
        rsi_desc = "مؤشر القوة النسبية (RSI) غير متاح بشكل واضح حاليًا."
    elif rsi_val < 30:
        rsi_desc = f"RSI عند `{rsi_val:.1f}` → تشبّع بيعي واضح يعكس ضغطًا بيعيًا قويًا."
    elif rsi_val > 70:
        rsi_desc = f"RSI عند `{rsi_val:.1f}` → تشبّع شرائي واضح وقد يزيد احتمال حدوث جني أرباح."
    else:
        rsi_desc = f"RSI عند `{rsi_val:.1f}` → حيادي بدون تشبّع واضح."

    # توصيف الاتجاه من EMA
    if ema50 and ema200:
        if last_close < ema50 < ema200:
            trend_desc = "الاتجاه قصير المدى يميل للسلبية مع تداول السعر أسفل متوسط 50 يوم وأقرب من 200 يوم."
        elif last_close < ema200:
            trend_desc = "السعر أسفل متوسط 200 يوم، ما يعكس ضغوط هابطة متوسطة إلى طويلة المدى."
        elif last_close > ema50 > ema200:
            trend_desc = "الاتجاه العام يميل إلى الإيجابية مع تمركز السعر أعلى المتوسطات الرئيسية."
        else:
            trend_desc = "السعر يتذبذب بالقرب من المتوسطات المتحركة، ما يعكس حالة حيادية نسبية في الاتجاه."
    else:
        trend_desc = "لا توجد بيانات كافية لحساب متوسطات 50 و 200 يوم بشكل موثوق."

    # توصيف حجم الحركة اليومية
    if change_pct <= -5:
        day_move_desc = f"اليوم يشهد هبوطًا قويًا بحوالي `{change_pct:.2f}%` مقارنة بإغلاق الأمس."
    elif change_pct >= 5:
        day_move_desc = f"اليوم يشهد صعودًا قويًا بحوالي `{change_pct:.2f}%` مقارنة بإغلاق الأمس."
    elif change_pct < -1:
        day_move_desc = f"اليوم يميل للهبوط بحوالي `{change_pct:.2f}%`."
    elif change_pct > 1:
        day_move_desc = f"اليوم يميل للصعود بحوالي `{change_pct:.2f}%`."
    else:
        day_move_desc = f"تغيّر اليوم محدود عند حوالي `{change_pct:.2f}%`."

    # نص التقرير + التحذير
    today = datetime.utcnow().strftime("%Y-%m-%d")

    text = (
        f"تصحيح تاريخ التحليل ✅\n\n"
        f"🧭 *تحليل الذكاء الاصطناعي لسوق البيتكوين* – {today}\n\n"
        f"🏦 *نظرة عامة على السوق:*\n"
        f"السعر الحالي للبيتكوين يدور حول `{price_txt}` دولار.\n"
        f"{day_move_desc}\n"
        f"يتداول السعر حاليًا بين قاعٍ تقريبي عند `{recent_low_txt}` وقمّةٍ قريبة من `{recent_high_txt}` "
        f"ضمن نطاق يومي/قصير المدى.\n\n"
        f"---\n"
        f"📊 *المؤشرات الفنية:*\n"
        f"- {rsi_desc}\n"
        f"- {trend_desc}\n"
        f"- النطاق السعري الأخير يعكس توازناً بين المشترين والبائعين ما بين `{recent_low_txt}` و `{recent_high_txt}`.\n\n"
        f"---\n"
        f"💎 *تقييم الوضع العام:*\n\n"
        f"استثماريًا:\n"
        f"- التماسك أعلى المنطقة `{level_mid1_txt} – {level_mid2_txt}` يعد إشارة أولية لتحسن قصير المدى.\n"
        f"- الإغلاق المستمر أعلى `{level_up_txt}` يفتح المجال لحركة صعودية أوسع على المدى المتوسط.\n\n"
        f"مضاربيًا:\n"
        f"- في حال زيادة التذبذب أو الهبوط الحاد، يُفضَّل تقليل حجم المخاطرة والابتعاد عن المراكز عالية الرافعة.\n\n"
        f"---\n"
        f"⚙️ *التوقعات القادمة (وفق البيانات الحالية):*\n"
        f"- التماسك أعلى `{level_mid2_txt}` يعزّز فرص استمرار الاستقرار أو محاولات صعود.\n"
        f"- كسر واضح ودائم أسفل `{recent_low_txt}` قد يفتح مجالًا لتصحيح أعمق.\n\n"
        f"---\n"
        f"📌 *الملخص النهائي:*\n"
        f"> السوق حاليًا يتحرك في إطار فني يوازن بين الضغط البيعي ومحاولات الشراء، مع حساسية واضحة "
        f"حول المستويات `{level_mid1_txt}` و `{level_mid2_txt}`.\n"
        f"التركيز حاليًا يكون على مراقبة هذه المناطق، وعدم الإفراط في المخاطرة قبل تأكيد اتجاه أوضح.\n\n"
        f"---\n"
        f"⚠️ *رسالة اليوم من IN CRYPTO Ai:*\n"
        f"> التعامل مع البيتكوين الآن يحتاج إلى صبر وانضباط في إدارة رأس المال.\n"
        f"تذكَّر أن الهدف ليس دخول كل حركة في السوق، بل اختيار الفرص الواضحة فقط.\n"
        f"IN CRYPTO Ai 🤖"
    )

    return text


def analyze_btc_for_alert(candles):
    """
    يقرر هل يتم إرسال تنبيه خاص بالبيتكوين الآن أم لا.
    يرجع (should_alert, reason_text, report_text)
    """
    closes = [c["close"] for c in candles]
    last_candle = candles[-1]
    prev_candle = candles[-2]

    last_close = last_candle["close"]
    prev_close = prev_candle["close"]

    change_pct = (last_close - prev_close) / prev_close * 100 if prev_close != 0 else 0

    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    rsi_val = rsi(closes, 14)

    reason = None

    # شروط بسيطة "للخطر"
    if rsi_val is not None and rsi_val < 30 and change_pct < -2:
        reason = "تشبّع بيعي قوي مع هبوط يومي واضح، ما يعكس حالة ضغط بيعي متزايد."
    elif change_pct <= -5:
        reason = "هبوط يومي حاد يتجاوز 5٪ تقريبًا، ما قد يشير لموجة تصحيح أو ذعر بيعي."
    elif ema50 and ema200 and last_close < ema50 < ema200 and change_pct < -2:
        reason = "كسر سلبي أسفل المتوسطات المتحركة الرئيسية مع هبوط يومي ملحوظ."

    if not reason:
        return False, None, None

    report = build_btc_market_report(candles)
    # نضيف فقرة تحذير أقوى فى آخر التقرير
    alert_tail = (
        "\n\n⚠️ *تنبيه خاص من نظام IN CRYPTO Ai:*\n"
        f"> تم رصد ظروف سوقية قد تحمل مخاطر هبوط أو تذبذب عنيف.\n"
        f"{reason}\n"
        "يُفضَّل في مثل هذه الأوقات حماية رأس المال، تقليل حجم المراكز، "
        "والتأكد من وجود خطط واضحة لوقف الخسارة."
    )
    report_with_alert = report + alert_tail
    return True, reason, report_with_alert


def btc_monitor_loop():
    """
    حلقة مراقبة البيتكوين فى الخلفية.
    تستدعى كل فترة (مثلاً كل 30 دقيقة) وتقرر هل تبعت تنبيه ولا لا.
    """
    global LAST_BTC_ALERT_STATE, LAST_BTC_ALERT_TS

    while True:
        try:
            logging.info("BTC monitor: checking market...")
            candles = get_binance_klines("BTCUSDT", limit=200)
            should_alert, reason, text = analyze_btc_for_alert(candles)

            now_ts = time.time()

            if should_alert:
                # تبعت تنبيه فقط لو:
                # - إما الحالة السابقة كانت عادية
                # - أو عدى أكتر من ساعة على آخر تنبيه
                if LAST_BTC_ALERT_STATE != "warning" or (now_ts - LAST_BTC_ALERT_TS) > BTC_ALERT_COOLDOWN:
                    logging.info(f"BTC monitor: sending alert. Reason: {reason}")
                    send_message(OWNER_CHAT_ID, text)
                    LAST_BTC_ALERT_STATE = "warning"
                    LAST_BTC_ALERT_TS = now_ts
                else:
                    logging.info("BTC monitor: warning detected but still under cooldown.")
            else:
                LAST_BTC_ALERT_STATE = "normal"

        except Exception as e:
            logging.error(f"BTC monitor error: {e}")

        # عشان الخطة المجانية ما تتخنقش، نخليها كل 30 دقيقة
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
                "يمكنك طلب تحليل فني يومي لأي عملة كالتالي:\n"
                "› `/coin btcusdt`\n"
                "أو مباشرةً:\n"
                "› `/btc`\n\n"
                "🔔 بالإضافة إلى ذلك، يقوم البوت بمراقبة البيتكوين على الإطار اليومي، "
                "وفي حال ظهور ظروف خطيرة أو حركة قوية، سيقوم بإرسال تقرير وتحذير تلقائيًا إلى هذا الحساب. 🤖"
            )
            send_message(chat_id, welcome)
            return "OK", 200

        # باقي الأوامر
        if text.startswith("/"):
            parts = text[1:].split()
            if not parts:
                send_message(chat_id, "❗ من فضلك اكتب الرمز بعد الأمر، مثل: `/coin btcusdt` أو `/btc`.")
                return "OK", 200

            cmd = parts[0].lower()

            # أمر تقرير البيتكوين الشامل يدويًا (للاختبار/الاستخدام اليدوي)
            if cmd in ("btc_report", "btcreport"):
                try:
                    candles = get_binance_klines("BTCUSDT", limit=200)
                    report = build_btc_market_report(candles)
                    send_message(chat_id, report)
                except Exception as e:
                    logging.error(f"Error building BTC report: {e}")
                    send_message(chat_id, "⚠️ تعذّر إنشاء تقرير البيتكوين الآن، جرّب مرة أخرى لاحقًا.")
                return "OK", 200

            # أمر /coin
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
                user_symbol_clean = user_symbol_clean.replace("USDT", "")
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
# ضبط الويبهوك وتشغيل السيرفر + تشغيل مراقبة BTC
# ==========================

def setup_webhook():
    """
    ضبط الويبهوك تلقائيًا مع عنوان Koyeb.
    """
    url = f"{TELEGRAM_API_URL}/setWebhook"
    webhook_url = APP_BASE_URL.rstrip("/") + "/webhook"
    try:
        r = requests.get(url, params={"url": webhook_url}, timeout=10)
        logging.info(f"setWebhook response: {r.status_code} - {r.text}")
    except Exception as e:
        logging.error(f"Error setting webhook: {e}")


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
