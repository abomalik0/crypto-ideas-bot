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

    # نعيد سبب مجمّع
    joined = " ".join(reasons)
    return joined


def format_smart_alert() -> str:
    """
    تحذير متكامل للمستخدم العادى
    (نتيجة نهائية من كل المؤشرات بدون تفاصيل المدارس).
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

    # مستويات تقريبية للمضاربين / المستثمرين
    support_zone = round(low * 0.98, 0)
    defence_zone = round(low * 0.97, 0)
    short_invalid = round(high * 1.02, 0)
    invest_alert_up = round(high * 1.03, 0)

    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    header = "⚠️ <b>تنبيه هام — السوق يدخل مرحلة حساسة</b>" if risk_reason else "ℹ️ <b>تحديث حالة السوق</b>"

    alert = f"""
{header}
📅 <b>التاريخ:</b> {today_str}

🏛 <b>البيتكوين:</b>
- السعر الحالى: <b>${price:,.0f}</b>
- تغير آخر 24 ساعة: <b>%{change:+.2f}</b>
- مدى الحركة اليومى: <b>{range_pct:.2f}%</b>

📊 <b>صورة السوق المختصرة:</b>
- {strength_label}
- {liquidity_pulse}

⚙️ <b>مستوى المخاطر (نظام التحذير الذكى):</b>
- المخاطر حالياً: {risk['emoji']} <b>{risk_level_text}</b>
- {risk['message']}
"""

    if risk_reason:
        alert += f"\n🚨 <b>أسباب التحذير:</b> {risk_reason}\n"

    alert += f"""
💼 <b>استثماريًا (أرقام تقريبية):</b>
- الحفاظ على المراكز يكون أفضل طالما السعر فوق منطقة <b>${support_zone:,.0f}</b>.
- كسر واضح أسفل <b>${defence_zone:,.0f}</b> يزيد احتمال تصحيح أعمق.

⚡ <b>مضاربيًا (تداول قصير المدى):</b>
- يُفضّل تجنب الرافعة العالية فى أوقات التقلب الحالى.
- سيناريو الحذر: أى إغلاق قوى أعلى من <b>${short_invalid:,.0f}</b> يلغى سيناريو الهبوط القصير.
- سيناريو تحسن قوى: عودة سعر البيتكوين والإغلاق المستقر فوق <b>${invest_alert_up:,.0f}</b> تعيد الإيجابية تدريجياً.

🤖 <b>رسالة IN CRYPTO Ai:</b>
- اعتبر إدارة رأس المال جزء أساسى من الاستراتيجية، مش إضافة اختيارية.
- لو السوق فى وضع ضبابى، أحياناً أفضل صفقة هى <b>عدم الدخول</b> حتى تتضح الصورة أكثر.
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
            "➤ <code>/alert</code> — تنبيه ذكى مدمج (للمستخدم العادى).\n"
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

    # /alert - تنبيه ذكى مختصر
    if lower_text == "/alert":
        reply = format_smart_alert()
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
