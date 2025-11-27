import os
import logging
import requests
from datetime import datetime
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

# ID بتاعك إنت بس للأوامر البرو
ADMIN_CHAT_ID = 669209875  # عدّله لو احتجت

# إعداد اللوج
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Flask
app = Flask(__name__)


# ==============================
#  دوال مساعدة لـ Telegram API
# ==============================

def send_message(chat_id: int, text: str, parse_mode: str = "HTML"):
    """إرسال رسالة عادية."""
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

    # لو ما نجحش، جرّب KuCoin
    data = fetch_from_kucoin(kucoin_symbol)
    if data:
        return data

    return None


# ==============================
#     صياغة رسالة التحليل للعملة
# ==============================

def format_analysis(user_symbol: str) -> str:
    """
    يرجّع نص التحليل النهائى لإرساله لتليجرام.
    فيه دعم تلقائى لأى رمز (BTC, VAI, ...).
    """
    data = fetch_price_data(user_symbol)
    if not data:
        # لو فشلنا فى Binance و KuCoin
        return (
            "⚠️ لا يمكن جلب بيانات هذه العملة الآن.\n"
            "تأكد من الرمز (مثال: <code>BTC</code> أو <code>BTCUSDT</code>) "
            "وحاول مرة أخرى."
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

    # RSI تجريبى مبنى على نسبة التغير (مش RSI حقيقى)
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

{ai_note}
""".strip()

    return msg


# ==============================
#  محرك قوة السوق والسيولة والـ Risk
# ==============================

def compute_market_metrics() -> dict | None:
    """
    يعتمد فقط على BTCUSDT من Binance/KuCoin.
    يرجّع dict فيها:
    - price, change_pct, high, low
    - range_pct
    - volatility_score
    - strength_label
    - liquidity_pulse
    """
    data = fetch_price_data("BTCUSDT")
    if not data:
        return None

    price = data["price"]
    change = data["change_pct"]
    high = data["high"]
    low = data["low"]

    # مدى الحركة كنسبة مئوية
    if price > 0 and high >= low:
        range_pct = ((high - low) / price) * 100.0
    else:
        range_pct = 0.0

    # درجة التقلب من 0 → 100
    volatility_raw = abs(change) * 1.5 + range_pct
    volatility_score = max(0.0, min(100.0, volatility_raw))

    # قوة الاتجاه / قوة السوق
    if change >= 3:
        strength_label = "صعود قوى للبيتكوين وزخم واضح."
    elif change >= 1:
        strength_label = "صعود هادئ مع تحسن تدريجى فى الزخم."
    elif change > -1:
        strength_label = "حركة متذبذبة بدون اتجاه واضح."
    elif change > -3:
        strength_label = "هبوط خفيف مع ضغط بيعى ملحوظ."
    else:
        strength_label = "هبوط قوى مع ضغوط بيعية عالية."

    # نبض السيولة (دخول/خروج)
    if change >= 2 and range_pct <= 5:
        liquidity_pulse = "السيولة تميل إلى الدخول للسوق بشكل منظم."
    elif change >= 2 and range_pct > 5:
        liquidity_pulse = "صعود سريع مع تقلب عالى → قد يكون فيه تصريف جزئى."
    elif -2 < change < 2:
        liquidity_pulse = "السيولة متوازنة تقريباً بين المشترين والبائعين."
    elif change <= -2 and range_pct > 4:
        liquidity_pulse = "خروج سيولة واضح من السوق مع هبوط ملحوظ."
    else:
        liquidity_pulse = "يوجد بعض الضغوط البيعية لكن بدون ذعر كبير."

    return {
        "price": price,
        "change_pct": change,
        "high": high,
        "low": low,
        "range_pct": range_pct,
        "volatility_score": volatility_score,
        "strength_label": strength_label,
        "liquidity_pulse": liquidity_pulse,
    }


def evaluate_risk_level(change_pct: float, volatility_score: float) -> dict:
    """
    محرك المخاطر:
    يرجّع:
    - level: low / medium / high
    - emoji
    - message
    """
    risk_score = abs(change_pct) + (volatility_score * 0.4)

    if risk_score < 25:
        level = "low"
        emoji = "🟢"
        message = (
            "المخاطر حاليًا منخفضة نسبيًا، السوق يتحرك بهدوء مع إمكانية "
            "الدخول بشرط الالتزام بمناطق وقف الخسارة."
        )
    elif risk_score < 50:
        level = "medium"
        emoji = "🟡"
        message = (
            "المخاطر حالياً متوسطة، الحركة السعرية بها تقلب واضح، "
            "ويُفضّل تقليل حجم الصفقات واستخدام إدارة مخاطر منضبطة."
        )
    else:
        level = "high"
        emoji = "🔴"
        message = (
            "المخاطر حالياً مرتفعة، السوق يشهد تقلبات قوية أو هبوط حاد، "
            "ويُفضّل تجنب الدخول العشوائى والتركيز على حماية رأس المال."
        )

    return {
        "level": level,
        "emoji": emoji,
        "message": message,
        "score": risk_score,
    }


# ==============================
#   تقرير السوق /market الحالى
# ==============================

def format_market_report() -> str:
    """
    تقرير سوق كامل مبنى فقط على BTC:
    - قوة الاتجاه
    - نبض السيولة
    - التقلب
    - تقييم المخاطر
    """
    metrics = compute_market_metrics()
    if not metrics:
        return (
            "⚠️ تعذّر جلب بيانات السوق العامة حاليًا.\n"
            "حاول مرة أخرى بعد قليل."
        )

    price = metrics["price"]
    change = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    volatility_score = metrics["volatility_score"]
    strength_label = metrics["strength_label"]
    liquidity_pulse = metrics["liquidity_pulse"]

    risk = evaluate_risk_level(change, volatility_score)
    risk_level = risk["level"]
    risk_emoji = risk["emoji"]
    risk_message = risk["message"]

    if risk_level == "low":
        risk_level_text = "منخفض"
    elif risk_level == "medium":
        risk_level_text = "متوسط"
    else:
        risk_level_text = "مرتفع"

    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    report = f"""
✅ <b>تحليل الذكاء الاصطناعى لسوق الكريبتو (مبنـى على حركة البيتكوين)</b>
📅 <b>التاريخ:</b> {today_str}

🏛 <b>نظرة عامة على البيتكوين:</b>
- السعر الحالى للبيتكوين: <b>${price:,.0f}</b>
- نسبة تغير آخر 24 ساعة: <b>%{change:+.2f}</b>

📈 <b>قوة الاتجاه (Market Strength):</b>
- {strength_label}
- مدى حركة اليوم بالنسبة للسعر: <b>{range_pct:.2f}%</b>
- درجة التقلب (من 0 إلى 100): <b>{volatility_score:.1f}</b>

💧 <b>نبض السيولة (Liquidity Pulse):</b>
- {liquidity_pulse}

⚙️ <b>مستوى المخاطر (نظام التحذير الذكى):</b>
- المخاطر حالياً عند مستوى: {risk_emoji} <b>{risk_level_text}</b>
- {risk_message}

📌 <b>تلميحات عامة للتداول:</b>
- يُفضّل التركيز على المناطق الواضحة للدعم والمقاومة بدلاً من مطاردة الحركة.
- فى أوقات التقلب العالى، إدارة رأس المال أهم من عدد الصفقات.

⚠️ <b>رسالة اليوم من IN CRYPTO Ai:</b>
- لا تحاول مطاردة كل حركة؛ ركّز على الفرص الواضحة فقط واعتبر إدارة المخاطر جزءًا من الاستراتيجية، وليس إضافة اختيارية.
- الصبر فى أوقات الضبابية يكون غالبًا أفضل من الدخول المتأخر فى حركة قوية.

IN CRYPTO Ai 🤖
""".strip()

    return report


def format_risk_test() -> str:
    """رسالة مختصرة لاختبار المخاطر السريع /risk_test"""
    metrics = compute_market_metrics()
    if not metrics:
        return (
            "⚠️ تعذّر جلب بيانات المخاطر حاليًا من المصدر.\n"
            "حاول مرة أخرى بعد قليل."
        )

    change = metrics["change_pct"]
    volatility_score = metrics["volatility_score"]
    risk = evaluate_risk_level(change, volatility_score)

    if risk["level"] == "low":
        level_text = "منخفض"
    elif risk["level"] == "medium":
        level_text = "متوسط"
    else:
        level_text = "مرتفع"

    msg = f"""
⚙️ <b>اختبار المخاطر السريع</b>

تغير البيتكوين خلال 24 ساعة: <b>%{change:+.2f}</b>
درجة التقلب الحالية: <b>{volatility_score:.1f}</b> / 100
المخاطر الحالية: {risk['emoji']} <b>{level_text}</b>

{risk['message']}

💡 هذه القراءة مبنية بالكامل على حركة البيتكوين الحالية بدون أى مزود بيانات إضافى.
""".strip()

    return msg


# ==============================
#   نظام التحذير الذكى (Alerts)
# ==============================

def detect_alert_condition(metrics: dict, risk: dict) -> str | None:
    """
    يحدّد لو فيه حالة تستحق إرسال تحذير قوى.
    يرجع سبب نصى لو فى تنبيه، أو None لو مفيش.
    """
    price = metrics["price"]
    change = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    volatility_score = metrics["volatility_score"]
    risk_level = risk["level"]

    reasons = []

    # هبوط أو صعود حاد
    if change <= -3:
        reasons.append("هبوط حاد فى البيتكوين أكبر من -3% خلال 24 ساعة.")
    elif change >= 4:
        reasons.append("صعود قوى وسريع فى البيتكوين أكبر من +4% خلال 24 ساعة.")

    # تقلب عالى
    if volatility_score >= 60 or range_pct >= 7:
        reasons.append("درجة التقلب مرتفعة بشكل ملحوظ فى الجلسة الحالية.")

    # مستوى المخاطر
    if risk_level == "high":
        reasons.append("محرك المخاطر يشير إلى مستوى <b>مرتفع</b> حالياً.")

    if not reasons:
        return None

    joined = " ".join(reasons)
    logger.info("Alert condition detected: %s | price=%s change=%.2f range=%.2f vol=%.1f",
                joined, price, change, range_pct, volatility_score)
    return joined


def format_smart_alert() -> str:
    """
    تحذير متكامل بصيغة قريبة من النموذج المطلوب:
    - ملخص السوق
    - مؤشرات فنية
    - On-Chain تقديرى
    - نماذج فنية + مستويات استثمارية ومضاربية
    """
    metrics = compute_market_metrics()
    if not metrics:
        return (
            "⚠️ تعذّر جلب بيانات السوق حالياً من المزود.\n"
            "حاول مرة أخرى بعد قليل."
        )

    price = metrics["price"]
    change = metrics["change_pct"]
    high = metrics["high"]
    low = metrics["low"]
    range_pct = metrics["range_pct"]
    volatility_score = metrics["volatility_score"]
    strength_label = metrics["strength_label"]
    liquidity_pulse = metrics["liquidity_pulse"]

    risk = evaluate_risk_level(change, volatility_score)
    risk_reason = detect_alert_condition(metrics, risk)

    # ============================
    #  مؤشرات ذكاء اصطناعى مبسطة
    # ============================

    # RSI تقريبى مبنى على التغير والمدى
    rsi_raw = 50 + (change * 1.3) - (range_pct * 0.3)
    rsi = max(10.0, min(90.0, rsi_raw))

    if rsi <= 30:
        rsi_state = "تشبع بيعى قوى."
    elif rsi >= 70:
        rsi_state = "تشبع شرائى محتمل."
    else:
        rsi_state = "منطقة حيادية إلى متوسطة."

    # MACD تقريبى
    if change <= -3:
        macd_view = "سلبى — ميل هابط واضح مع ضغط بيعى متزايد."
    elif change <= -1:
        macd_view = "سلبى خفيف — اتجاه هابط بدون انهيار حاد."
    elif change >= 3:
        macd_view = "إيجابى قوى — زخم صعودى واضح مع احتمال تصحيحات."
    elif change >= 1:
        macd_view = "إيجابى هادئ — صعود متدرج بدون اندفاع كبير."
    else:
        macd_view = "متذبذب — لا يوجد اتجاه واضح، حركة جانبية تقريبًا."

    # الزخم العام
    if abs(change) < 1 and range_pct < 3:
        momentum_view = "تراجع فى الزخم، الحركة ضعيفة ومتذبذبة."
    elif change < -2 and volatility_score > 50:
        momentum_view = "تراجع مستمر مع زخم هابط قوى، بدون إشارات انعكاس واضحة."
    elif change > 2 and volatility_score > 50:
        momentum_view = "زخم صعودى قوى لكن مع تقلب عالى (احذر مطاردة القمم)."
    else:
        momentum_view = "زخم متوسط يميل لاتجاه الحركة الحالية."

    # ============================
    #  On-Chain تقديرى
    # ============================

    if change <= -3 and volatility_score >= 50:
        onchain_1 = "📤 سلوك يشبه ضغط بيع قوى من المحافظ الكبيرة (تشبيه بضخ عملات للبورصات)."
        onchain_2 = "📉 التدفقات السلبية إلى البورصات مرجّحة فى هذه الحركة."
        onchain_3 = "📊 نشاط الشبكة منخفض نسبيًا من جانب المشترين الجدد."
    elif change <= -1:
        onchain_1 = "📤 توجد إشارات لضغط بيعى متوسط من العناوين الكبيرة."
        onchain_2 = "📉 التدفقات السلبية للبورصات فى ازدياد محدود."
        onchain_3 = "📊 نشاط الشبكة متوسط مع حذر واضح من المشترين."
    else:
        onchain_1 = "📥 لا تظهر إشارات قوية على بيع عنيف من الحيتان فى القراءة الحالية."
        onchain_2 = "📈 التدفقات تبدو متوازنة بين الدخول والخروج."
        onchain_3 = "📊 نشاط الشبكة مقبول، السوق ليس بلا مشترين تمامًا."

    # ============================
    #  النماذج الفنية التقريبية
    # ============================

    if change <= -2 and range_pct >= 4:
        pattern_channel = "❌ كسر قناة صاعدة أو منطقة دعم سابقة (Bearish Break تقريبى)."
    elif change < 0:
        pattern_channel = "⚠ ضعف شموع الصعود مؤخرًا مع ميل هابط واضح."
    else:
        pattern_channel = "ℹ لا يوجد كسر واضح لقناة صاعدة فى القراءة الحالية."

    # هارمونيك تقديرى
    if rsi <= 30 and change <= -2:
        harmonic_line = "❗ احتمالات لنموذج هارمونيك انعكاسى قرب مناطق دعم قوية (يحتاج تأكيد من الحركة القادمة)."
    else:
        harmonic_line = "ℹ لا يظهر نموذج هارمونيك واضح من منظور النظام الآلى حالياً."

    # ============================
    #  مستويات استثمارية / مضاربية
    # ============================

    # دعم حرِج تقريبى
    critical_support = round(low * 0.99, 0)
    deep_support_1 = round(low * 0.98, 0)
    deep_support_2 = round(low * 0.96, 0)

    # مستويات دخول استثمارى بعد تأكيد
    invest_no_entry_before = round(high * 1.02, 0)
    invest_good_zone_low = round(high * 1.06, 0)
    invest_good_zone_high = round(high * 1.08, 0)

    # مضاربة
    leverage_cancel_level = round(price * 1.01, 0)
    scalp_zone_low = round(low * 1.01, 0)
    scalp_zone_high = round(low * 1.03, 0)

    # اليوم والتاريخ
    weekday_names = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    now = datetime.utcnow()
    today_str = now.strftime("%Y-%m-%d")
    weekday_name = weekday_names[now.weekday()] if 0 <= now.weekday() < len(weekday_names) else "اليوم"

    header = "⚠️ تنبيه هام — السوق يدخل مرحلة خطر حقيقي" if (risk_reason or risk["level"] == "high") else "ℹ️ تحديث حالة السوق"

    alert = f"""
{header}

📅 اليوم: {weekday_name} — {today_str}
📉 البيتكوين الآن: ${price:,.0f} (تغير آخر 24 ساعة: % {change:+.2f})

---

🧭 ملخص سريع لوضع السوق

{strength_label}
{liquidity_pulse}
السعر يقترب من مناطق دعم مهمة تقريبية حول: ${critical_support:,.0f}.

---

📉 المؤشرات الفنية

RSI: عند تقريبًا {rsi:.0f} → {rsi_state}
MACD: {macd_view}
الحركة اليومية: % {change:+.2f} خلال آخر 24 ساعة.
الزخم: {momentum_view}

---

🔗 بيانات الـ On-Chain (قراءة تقديرية)

{onchain_1}
{onchain_2}
{onchain_3}
🧨 المخاطر الآن مرتفعة نسبيًا كلما زاد التقلب مع الهبوط.

---

🏛 النماذج الفنية النشطة

{pattern_channel}
{harmonic_line}

---

💎 استثماريًا

❌ لا دخول قبل إغلاق واضح فوق تقريبًا: ${invest_no_entry_before:,.0f}
✔ المستويات الجيدة للعودة (تقديريًا بعد تأكيد إيجابى): {invest_good_zone_low:,.0f}$ – {invest_good_zone_high:,.0f}$

---

⚡ مضاربيًا (بأرقام تقريبية)

⚠ إلغاء أى تداول برافعة عالية طالما السعر تحت تقريبًا: ${leverage_cancel_level:,.0f}
⚠ كسر منطقة الدعم الحرجة قرب: ${critical_support:,.0f} قد يفتح الطريق لمناطق أعمق مثل: ${deep_support_1:,.0f} ثم ${deep_support_2:,.0f}
✔ أفضل مناطق ارتداد سريعة محتملة (Scalp محتاط): {scalp_zone_low:,.0f}$ – {scalp_zone_high:,.0f}$ مع وقف خسارة صارم.

---

📌 رسالة IN CRYPTO Ai

> السوق الآن غير مستقر نسبيًا.
الأفضل هو الانتظار وتجنب المخاطرة المفرطة، واستخدام الرافعة المالية فقط فى أضيق الحدود
ومع خطة واضحة لوقف الخسارة.
أى دخول غير مدروس قد يؤدى إلى خسائر لا داعى لها.

IN CRYPTO Ai 🤖
""".strip()

    return alert


def format_pro_alert() -> str:
    """
    تنبيه احترافى /pro_alert — تفاصيل أكتر ليك إنت بس.
    نفس النتيجة العامة لكن مع توضيح أقوى لأسباب القرار.
    """
    metrics = compute_market_metrics()
    if not metrics:
        return (
            "⚠️ تعذّر جلب بيانات السوق حالياً من المزود.\n"
            "حاول مرة أخرى بعد قليل."
        )

    price = metrics["price"]
    change = metrics["change_pct"]
    high = metrics["high"]
    low = metrics["low"]
    range_pct = metrics["range_pct"]
    volatility_score = metrics["volatility_score"]
    strength_label = metrics["strength_label"]
    liquidity_pulse = metrics["liquidity_pulse"]

    risk = evaluate_risk_level(change, volatility_score)
    risk_reason = detect_alert_condition(metrics, risk)

    if risk["level"] == "low":
        risk_level_text = "منخفض"
    elif risk["level"] == "medium":
        risk_level_text = "متوسط"
    else:
        risk_level_text = "مرتفع"

    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    # مناطق تقريبية
    intraday_support = round(low * 0.99, 0)
    swing_support = round(low * 0.97, 0)
    intraday_resist = round(high * 1.01, 0)
    swing_resist = round(high * 1.03, 0)

    header = "⚠️ <b>Pro Alert — السوق فى منطقة خطر</b>" if risk_reason else "ℹ️ <b>Pro Alert — تحديث احترافى للسوق</b>"

    msg = f"""
{header}
📅 <b>التاريخ:</b> {today_str}

🏛 <b>البيتكوين:</b>
- السعر الحالى: <b>${price:,.0f}</b>
- تغير 24 ساعة: <b>%{change:+.2f}</b>
- مدى الحركة اليومى: <b>{range_pct:.2f}%</b>
- درجة التقلب (0 → 100): <b>{volatility_score:.1f}</b>

📊 <b>قراءة النظام (اتجاه + سيولة):</b>
- {strength_label}
- {liquidity_pulse}

⚙️ <b>محرك المخاطر:</b>
- المستوى الحالى: {risk['emoji']} <b>{risk_level_text}</b>
- سبب تقييم المخاطر: {risk['message']}
"""

    if risk_reason:
        msg += f"\n🚨 <b>تجميع أسباب التحذير:</b> {risk_reason}\n"

    msg += f"""
🎯 <b>استثمارياً (مدى متوسط):</b>
- منطقة دعم متابعة: حوالى <b>${swing_support:,.0f}</b>.
- عودة الإيجابية القوية تبدأ مع إغلاق مستقر أعلى <b>${swing_resist:,.0f}</b>.

⚡ <b>مضاربياً (قصير المدى):</b>
- دعم تداول يومى تقريبى: <b>${intraday_support:,.0f}</b>.
- مقاومة تداول يومى تقريبية: <b>${intraday_resist:,.0f}</b>.
- فى حالة بقاء التقلب الحالى، الأفضل تخفيض حجم العقود وتجنّب ملاحقة الحركة العنيفة.

🤖 <b>ملاحظة IN CRYPTO Ai (وضع Pro):</b>
- استخدم هذه القراءة كفلتر أولى قبل أى نماذج فنية أو هارمونيك.
- لو المؤشرات الكلاسيكية عندك بتدى صعود لكن محرك المخاطر هنا فى حالة خطر، اعتبر الدخول جزء صغير فقط من رأس المال أو انتظر تأكيد أقوى.
""".strip()

    return msg


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
            "➤ <code>/coin hook</code> أو أى رمز آخر.\n\n"
            "لتحليل السوق العام ونظام التحذير الذكى:\n"
            "➤ <code>/market</code> — تقرير سوق مبنى على حركة البيتكوين.\n"
            "➤ <code>/risk_test</code> — اختبار سريع لمستوى المخاطر.\n"
            "➤ <code>/pro_alert</code> — تنبيه احترافى خاص (للأدمن فقط).\n\n"
            "البوت يحاول أولاً جلب البيانات من Binance، "
            "وإذا لم يجد العملة يحاول تلقائيًا من KuCoin."
        )
        send_message(chat_id, welcome)
        return jsonify(ok=True)

    # /btc
    if lower_text == "/btc":
        reply = format_analysis("BTCUSDT")
        send_message(chat_id, reply)
        return jsonify(ok=True)

    # /vai
    if lower_text == "/vai":
        reply = format_analysis("VAIUSDT")
        send_message(chat_id, reply)
        return jsonify(ok=True)

    # /market - تقرير السوق العام
    if lower_text == "/market":
        reply = format_market_report()
        send_message(chat_id, reply)
        return jsonify(ok=True)

    # /risk_test - اختبار المخاطر السريع
    if lower_text == "/risk_test":
        reply = format_risk_test()
        send_message(chat_id, reply)
        return jsonify(ok=True)

    # /pro_alert - تنبيه احترافى للأدمن فقط
    if lower_text == "/pro_alert":
        if chat_id != ADMIN_CHAT_ID:
            send_message(
                chat_id,
                "❌ هذا الأمر مخصص للاستخدام الإدارى فقط.",
            )
            return jsonify(ok=True)
        reply = format_pro_alert()
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
#   مسار المراقبة التلقائية /auto_alert
# ==============================

@app.route("/auto_alert", methods=["GET"])
def auto_alert():
    """
    مسار لاستخدامه مع Cron Job (مثلاً من Koyeb):
    - يراقب السوق.
    - لو فيه حالة خطر حقيقية → يبعت التحذير للأدمن فقط.
    - لو مفيش خطر → ميبعتش رسالة، ويرجع alert_sent=false.
    """
    metrics = compute_market_metrics()
    if not metrics:
        logger.warning("auto_alert: cannot fetch market metrics")
        return jsonify(ok=False, alert_sent=False, reason="no_metrics"), 200

    risk = evaluate_risk_level(metrics["change_pct"], metrics["volatility_score"])
    reason = detect_alert_condition(metrics, risk)

    if not reason:
        # لا يوجد سبب كافى لإرسال تحذير
        logger.info("auto_alert: no alert condition, skipping send.")
        return jsonify(ok=True, alert_sent=False, reason="no_alert_condition"), 200

    # يوجد حالة خطر → نبعت التحذير للأدمن
    alert_text = format_smart_alert()
    send_message(ADMIN_CHAT_ID, alert_text)
    logger.info("auto_alert: alert sent to ADMIN_CHAT_ID. reason=%s", reason)

    return jsonify(ok=True, alert_sent=True, reason="alert_sent"), 200


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
    # تشغيل Flask على 8080
    app.run(host="0.0.0.0", port=8080)
