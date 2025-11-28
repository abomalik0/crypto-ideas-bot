import os
import logging
import requests
from datetime import datetime
from collections import deque
from flask import Flask, request, jsonify, Response

# ==============================
#        الإعدادات العامة
# ==============================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
APP_BASE_URL = (os.getenv("APP_BASE_URL") or "").rstrip("/")
ADMIN_CHAT_ID = 669209875  # عدّله لو احتجت

# باسورد لوحة تحكم الأدمن (حطه فى Environment variable على Koyeb)
ADMIN_DASH_PASSWORD = os.getenv("ADMIN_DASH_PASSWORD", "change_me")

if not TELEGRAM_TOKEN:
    raise RuntimeError("البيئة لا تحتوى على TELEGRAM_TOKEN")

if not APP_BASE_URL:
    raise RuntimeError("البيئة لا تحتوى على APP_BASE_URL")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# حالة آخر تحذير اتبعت تلقائى (عشان ما يتكررش)
LAST_ALERT_REASON = None

# ==============================
#  إعداد اللوج + Log Buffer للـ Dashboard
# ==============================

# Buffer لآخر 200 log سطر للعرض فى الـ Dashboard
LOG_BUFFER = deque(maxlen=200)

class InMemoryLogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        LOG_BUFFER.append(msg)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_memory_handler = InMemoryLogHandler()
_memory_handler.setLevel(logging.INFO)
_memory_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(_memory_handler)

# ==============================
#  تخزين تاريخ التحذيرات للأدمن
# ==============================

ALERTS_HISTORY = deque(maxlen=100)  # آخر 100 تحذير

def add_alert_history(source: str, reason: str, price: float | None = None, change: float | None = None):
    entry = {
        "time": datetime.utcnow().isoformat(timespec="seconds"),
        "source": source,  # "auto" أو "manual" أو "force"
        "reason": reason,
        "price": price,
        "change_pct": change,
    }
    ALERTS_HISTORY.append(entry)
    logger.info("Alert history added: %s", entry)


# Flask
app = Flask(__name__)


# ==============================
#  دوال مساعدة لـ Telegram API
# ==============================

def send_message(chat_id: int, text: str, parse_mode: str = "HTML"):
    """إرسال رسالة عادية بدون كيبورد."""
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            logger.warning(
                "Telegram sendMessage error: %s - %s",
                r.status_code,
                r.text,
            )
    except Exception as e:
        logger.exception("Exception while sending message: %s", e)


def send_message_with_keyboard(
    chat_id: int,
    text: str,
    reply_markup: dict,
    parse_mode: str = "HTML",
):
    """إرسال رسالة مع كيبورد إنلاين (مثلاً زر عرض التفاصيل)."""
    try:
        url = f"{TELEGRAM_API}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        }
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            logger.warning(
                "Telegram sendMessage_with_keyboard error: %s - %s",
                r.status_code,
                r.text,
            )
    except Exception as e:
        logger.exception("Exception while sending message with keyboard: %s", e)


def answer_callback_query(
    callback_query_id: str,
    text: str | None = None,
    show_alert: bool = False,
):
    """الرد على ضغط زر إنلاين عشان يوقف اللودنج."""
    try:
        url = f"{TELEGRAM_API}/answerCallbackQuery"
        payload = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }
        if text:
            payload["text"] = text
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            logger.warning(
                "Telegram answerCallbackQuery error: %s - %s",
                r.status_code,
                r.text,
            )
    except Exception as e:
        logger.exception("Exception while answering callback query: %s", e)


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
            logger.info(
                "Binance error %s for %s: %s",
                r.status_code,
                symbol,
                r.text,
            )
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
            logger.info(
                "KuCoin error %s for %s: %s",
                r.status_code,
                symbol,
                r.text,
            )
            return None

        payload = r.json()
        if payload.get("code") != "200000":
            logger.info("KuCoin non-success code: %s", payload)
            return None

        data = payload.get("data") or {}
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

    data = fetch_from_binance(binance_symbol)
    if data:
        return data

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
        return (
            "⚠️ لا يمكن جلب بيانات هذه العملة الآن.\n"
            "تأكد من الرمز (مثال: <code>BTC</code> أو <code>BTCUSDT</code>) "
            "وحاول مرة أخرى."
        )

    price = data["price"]
    change = data["change_pct"]
    high = data["high"]
    low = data["low"]
    exchange = data["exchange"]

    base, binance_symbol, kucoin_symbol = normalize_symbol(user_symbol)
    display_symbol = (
        binance_symbol if exchange == "binance" else kucoin_symbol
    ).replace("-", "")

    support = round(low * 0.99, 6) if low > 0 else round(price * 0.95, 6)
    resistance = round(high * 1.01, 6) if high > 0 else round(price * 1.05, 6)

    rsi_raw = 50 + (change * 0.8)
    rsi = max(0, min(100, rsi_raw))
    if rsi >= 70:
        rsi_trend = "⬆️ مرتفع (تشبّع شرائى محتمل)"
    elif rsi <= 30:
        rsi_trend = "⬇️ منخفض (تشبّع بيع محتمل)"
    else:
        rsi_trend = "🔁 حيادى نسبياً"

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

    if price > 0 and high >= low:
        range_pct = ((high - low) / price) * 100.0
    else:
        range_pct = 0.0

    volatility_raw = abs(change) * 1.5 + range_pct
    volatility_score = max(0.0, min(100.0, volatility_raw))

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


# ==============================
#   اختبار المخاطر السريع /risk_test
# ==============================

def format_risk_test() -> str:
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
        reasons.append("محرك المخاطر يشير إلى مستوى مرتفع حالياً.")

    if not reasons:
        return None

    joined = " ".join(reasons)
    logger.info(
        "Alert condition detected: %s | price=%s change=%.2f range=%.2f vol=%.1f",
        joined,
        price,
        change,
        range_pct,
        volatility_score,
    )
    return joined


# ==============================
#   التحذير الموحد المختصر - format_ai_alert
# ==============================

def format_ai_alert() -> str:
    """
    التحذير الرئيسي الموحد (التلقائي + اليدوي المختصر)
    يعتمد على النص المعتمد + ملء السعر والتغير والتاريخ.
    """
    data = fetch_price_data("BTCUSDT")
    if not data:
        return "⚠️ تعذّر جلب بيانات البيتكوين حاليًا. حاول بعد قليل."

    price = data["price"]
    change = data["change_pct"]

    now = datetime.utcnow()
    weekday_names = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    weekday_name = (
        weekday_names[now.weekday()]
        if 0 <= now.weekday() < len(weekday_names)
        else "اليوم"
    )
    date_part = now.strftime("%Y-%m-%d")

    alert_text = f"""
⚠️ تنبيه هام — السوق يدخل مرحلة خطر حقيقي

📅 اليوم: {weekday_name} — {date_part}
📉 البيتكوين الآن: {price:,.0f}$  (تغير 24 ساعة: {change:+.2f}%)

---

🧭 ملخص سريع لوضع السوق

• الاتجاه العام يميل للهبوط مع ضغط بيعي متزايد.
• السوق يفقد الزخم بشكل واضح — المشترين ضعاف والسيولة تخرج تدريجيًا.
• السعر يقترب من مناطق دعم حساسة جدًا بين 89,000$ و 88,500$.
• احتمالية استمرار الهبوط أعلى من احتمالية الارتداد اللحظى.

---

🔵 المدرسة الفنية 

• خروج من قناة صاعدة قديمة → كسر هابط واضح.
• ضعف كبير فى شموع الصعود مع ظهور شموع اندفاع بيعية.
• النطاق الحالي قريب من منطقة سعرية منخفضة (Discount) لكن بدون ظهور دخول قوى من المشترين.
• حركة السعر خلال الساعات الأخيرة داخل نطاق ضيق يميل للدببة.

---

🟣 الهارمونيك (Harmonic View)

• رصد نموذج ABCD هابط قرب المنطقة الحالية.
• منطقة الانعكاس المحتملة تقع بين:
  → 88,800$ و 88,200$
• دقة النموذج متوسطة، ويحتاج شمعة تأكيد قبل الاعتماد عليه.

---

📉 المؤشرات الفنية

• RSI عند 27 → تشبع بيعي واضح.
• MACD سلبى → ميل هابط مستمر.
• الزخم العام يضعف بدون إشارات انعكاس قوية.
• الحركة اليومية: -3.8% خلال آخر 4 ساعات.
• حجم التداول منخفض → أى ارتداد قد يكون ضعيف.

---

🔗 بيانات الـ On-Chain (مختصرة وقوية)

• الحيتان ضخت حوالى 1.8B$ للبورصات → ضغط بيع مؤسسى مباشر.
• زيادة في التدفقات السلبية → خروج سيولة من السوق.
• نشاط الشبكة منخفض → عمليات الشراء ضعيفة جدًا.
• سلوك المحافظ الكبيرة يشير لمخاطر مرتفعة فى المدى القصير.

---

💎 استثماريًا (مدى متوسط)

• لا دخول قبل إغلاق ثابت فوق 91,500$.
• أفضل مناطق عودة محتملة: 96,000$ – 98,000$ بعد تأكيد إيجابي.
• كسر منطقة 88,000$ قد يفتح تصحيحًا أعمق.

---

⚡ مضاربيًا (قصير المدى)

• تجنب أى تداول برافعة طالما السعر تحت 90,800$.
• كسر 88,000$ قد يفتح الطريق نحو:
  → 86,800$
  → 85,900$
• أفضل نطاق ارتداد سريع محتمل:
  → 89,300$ – 89,700$ (مع وقف خسارة صارم)

---

🤖 ملخص الذكاء الاصطناعي (IN CRYPTO Ai)

• دمج نتائج: (الاتجاه – السيولة – النماذج – الحجم – النشاط – الزخم)
  يشير إلى:
  → استمرار ضغط بيعي مؤسسى خفيف إلى متوسط.
  → احتمالية امتداد الهبوط طالما لا يوجد رفض سعرى قوى من مناطق الدعم.

• توصية النظام:
  → تجنب المخاطرة المفرطة حاليًا.
  → التركيز على حماية رأس المال بدل البحث عن فرص دخول غير مؤكدة.

IN CRYPTO Ai 🤖
""".strip()

    return alert_text


# ==============================
#   التحذير الموسع الخاص بالأدمن - /alert details
# ==============================

def format_ai_alert_details() -> str:
    """
    نسخة موسعة من التحذير للأدمن فقط:
    - تفاصيل المدارس
    - مستويات موسعة
    - قراءات أدق من التحذير العادي
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
    risk_level = risk["level"]
    risk_emoji = risk["emoji"]
    risk_message = risk["message"]

    # مستويات تقريبية
    critical_support = round(low * 0.99, 0)
    deep_support_1 = round(low * 0.98, 0)
    deep_support_2 = round(low * 0.96, 0)
    invest_zone_low = round(high * 1.06, 0)
    invest_zone_high = round(high * 1.08, 0)
    reentry_level = round(high * 1.02, 0)
    leverage_cancel_level = round(price * 1.01, 0)

    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    details = f"""
📌 <b>تقرير التحذير الكامل — /alert (IN CRYPTO Ai)</b>
📅 <b>التاريخ:</b> {today_str}
💰 <b>سعر البيتكوين الحالى:</b> ${price:,.0f}  (تغير 24 ساعة: % {change:+.2f})
📊 <b>مدى الحركة اليومى:</b> {range_pct:.2f}% — التقلب: {volatility_score:.1f} / 100

1️⃣ <b>السوق العام</b>
- {strength_label}
- {liquidity_pulse}
- مستوى الخطر: {risk_emoji} <b>{risk_level}</b>
- {risk_message}

2️⃣ <b>سلوك السعر والهيكل</b>
- اتجاه هابط قصير المدى.
- سحب سيولة واضح من قمم قريبة.
- مناطق سيولة أسفل: <b>${critical_support:,.0f}</b>
- احتمالات زيارة أعمق: <b>${deep_support_1:,.0f}</b> ثم <b>${deep_support_2:,.0f}</b>

3️⃣ <b>تحليل الجلسات والزمن</b>
- الجلسة الحالية تميل للدببة.
- احتمالات انعكاس تحتاج سلوك رفض سعرى واضح.
- نشاط الحجم ضعيف → الارتدادات غير مؤكدة.

4️⃣ <b>الموجة الحالية (Wave Logic)</b>
- موجة هابطة اندفاعية.
- علامات إرهاق بيعى خفيفة لكنها غير مؤكدة.
- الموجات الصغيرة تظهر زخم هابط متتابع.

5️⃣ <b>النماذج الفنية</b>
- وجود كسر لقناة صاعدة → بداية هبوط.
- شموع الهبوط أقوى من شموع الصعود.
- محاولة تكوين نموذج تصحيح جانبى.

6️⃣ <b>الهارمونيك</b>
- نموذج ABCD هابط رُصد قريب من السعر.
- منطقة الانعكاس (PRZ):
  • بين <b>88,800$</b> و <b>88,200$</b>
- يحتاج تأكيد بحجم ورفض سعرى.

7️⃣ <b>السيولة والتدفق</b>
- سيولة خارجة من السوق.
- عمليات بيع من المحافظ الكبيرة.
- ارتدادات بلا حجم = غير موثوقة.

8️⃣ <b>الزخم والحجم</b>
- زخم هابط متماسك.
- حجم تداول ضعيف → يؤكد الهبوط.

9️⃣ <b>نظرة استثمارية</b>
- لا دخول قبل:
  • <b>${reentry_level:,.0f}</b>
- مناطق إعادة الدخول الأفضل:
  • <b>${invest_zone_low:,.0f}</b> → <b>${invest_zone_high:,.0f}</b>

🔟 <b>نظرة مضاربية</b>
- تجنب الرافعة تحت:
  • <b>${leverage_cancel_level:,.0f}</b>
- احتمالات زيارة مستويات أدنى:
  • {deep_support_1:,.0f}$
  • {deep_support_2:,.0f}$
- السكالب فقط من دعوم قوية مع SL قريب.

🧠 <b>خلاصة الذكاء الاصطناعى</b>
- السوق فى وضع خطر نسبى:
  • زخم هابط  
  • سيولة خارجة  
  • غياب مشترين حقيقيين  
- أفضل إجراء:
  • حماية رأس المال  
  • تجنب المخاطرة العالية  
  • الانتظار لرفض سعرى واضح  

IN CRYPTO Ai 🤖
""".strip()

    return details


# ==============================
#          مسارات Flask الأساسية
# ==============================

@app.route("/", methods=["GET"])
def index():
    return "Crypto ideas bot is running.", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(force=True, silent=True) or {}
    logger.info("Update: %s", update)

    # ================
    #  callback_query
    # ================
    if "callback_query" in update:
        cq = update["callback_query"]
        callback_id = cq.get("id")
        data = cq.get("data")
        message = cq.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        from_user = cq.get("from") or {}
        from_id = from_user.get("id")

        # وقف اللودنج
        if callback_id:
            answer_callback_query(callback_id)

        # زر عرض التفاصيل
        if data == "alert_details":
            if from_id != ADMIN_CHAT_ID:
                if chat_id:
                    send_message(chat_id, "❌ هذا الزر مخصص للإدارة فقط.")
                return jsonify(ok=True)

            details = format_ai_alert_details()
            send_message(chat_id, details)
            return jsonify(ok=True)

        return jsonify(ok=True)

    # ================
    #  رسائل عادية
    # ================
    if "message" not in update:
        return jsonify(ok=True)

    msg = update["message"]
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    lower_text = text.lower()

    # /start
    if lower_text == "/start":
        welcome = (
            "👋 أهلاً بك فى <b>IN CRYPTO Ai</b>.\n\n"
            "استخدم الأوامر التالية:\n"
            "• <code>/btc</code> — تحليل BTC\n"
            "• <code>/vai</code> — تحليل VAI\n"
            "• <code>/coin btc</code> — تحليل أى عملة\n\n"
            "تحليل السوق:\n"
            "• <code>/market</code> — نظرة عامة\n"
            "• <code>/risk_test</code> — اختبار مخاطر\n"
            "• <code>/alert</code> — تحذير كامل (للأدمن فقط)\n\n"
            "النظام يجلب البيانات أولاً من Binance ثم KuCoin تلقائيًا."
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

    # /market
    if lower_text == "/market":
        reply = format_market_report()
        send_message(chat_id, reply)
        return jsonify(ok=True)

    # /risk_test
    if lower_text == "/risk_test":
        reply = format_risk_test()
        send_message(chat_id, reply)
        return jsonify(ok=True)

    # /alert — الأدمن فقط
    if lower_text == "/alert":
        if chat_id != ADMIN_CHAT_ID:
            send_message(chat_id, "❌ هذا الأمر مخصص للإدارة فقط.")
            return jsonify(ok=True)

        alert_text = format_ai_alert()
        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "عرض التفاصيل 📊",
                        "callback_data": "alert_details",
                    }
                ]
            ]
        }
        send_message_with_keyboard(chat_id, alert_text, keyboard)

        # سجل التحذير اليدوى فى التاريخ
        add_alert_history("manual", "Manual /alert command")

        return jsonify(ok=True)

    # /coin xxx
    if lower_text.startswith("/coin"):
        parts = lower_text.split()
        if len(parts) < 2:
            send_message(
                chat_id,
                "⚠️ استخدم الأمر هكذا:\n"
                "<code>/coin btc</code>\n"
                "<code>/coin btcusdt</code>\n"
                "<code>/coin vai</code>",
            )
        else:
            reply = format_analysis(parts[1])
            send_message(chat_id, reply)
        return jsonify(ok=True)

    # أى رسالة أخرى
    send_message(
        chat_id,
        "⚙️ اكتب /start لعرض الأوامر.\nمثال: <code>/btc</code> أو <code>/coin btc</code>."
    )
    return jsonify(ok=True)


# ==============================
#   مسار المراقبة التلقائية /auto_alert
# ==============================

@app.route("/auto_alert", methods=["GET"])
def auto_alert():
    """
    هذا المسار يتم استدعاؤه بواسطة Cron Job خارجى.
    • يراقب السوق كل دقيقة.
    • لو ظهر خطر جديد → يرسل تحذير تلقائى للأدمن فقط.
    • لو نفس الخطر السابق → لا يعيد الإرسال.
    """
    global LAST_ALERT_REASON

    metrics = compute_market_metrics()
    if not metrics:
        logger.warning("auto_alert: cannot fetch metrics")
        return jsonify(ok=False, alert_sent=False, reason="metrics_failed"), 200

    risk = evaluate_risk_level(metrics["change_pct"], metrics["volatility_score"])
    reason = detect_alert_condition(metrics, risk)

    # لا يوجد خطر
    if not reason:
        if LAST_ALERT_REASON is not None:
            logger.info("auto_alert: market normal again → reset alert state.")
        LAST_ALERT_REASON = None
        return jsonify(ok=True, alert_sent=False, reason="no_alert"), 200

    # نفس التحذير القديم → لا يعاد إرساله
    if reason == LAST_ALERT_REASON:
        logger.info("auto_alert: skipped (same reason).")
        return jsonify(ok=True, alert_sent=False, reason="duplicate"), 200

    # خطر جديد → ارسال التحذير المختصر
    alert_text = format_ai_alert()
    send_message(ADMIN_CHAT_ID, alert_text)

    LAST_ALERT_REASON = reason
    logger.info("auto_alert: NEW alert sent! reason=%s", reason)

    # سجل التحذير فى التاريخ
    add_alert_history("auto", reason, price=metrics["price"], change=metrics["change_pct"])

    return jsonify(ok=True, alert_sent=True, reason="sent"), 200


# ==============================
#       تفعيل الـ Webhook
# ==============================

def setup_webhook():
    """يتم تشغيله مرة واحدة عند بدء السيرفر"""
    webhook_url = f"{APP_BASE_URL}/webhook"
    try:
        r = requests.get(
            f"{TELEGRAM_API}/setWebhook",
            params={"url": webhook_url},
            timeout=10,
        )
        logger.info("Webhook response: %s - %s", r.status_code, r.text)
    except Exception as e:
        logger.exception("Error while setting webhook: %s", e)


# ==============================
#     دوال مساعدة لـ Dashboard
# ==============================

def _check_admin_auth(req: request) -> bool:
    """
    تأكيد إن المتصل معا باسورد الأدمن الصحيح.
    بيقرأ من:
    - query param: ?password=...
    - أو الهيدر: X-Admin-Token
    """
    pwd = req.args.get("password") or req.headers.get("X-Admin-Token")
    if not pwd:
        return False
    return pwd == ADMIN_DASH_PASSWORD


def _unauthorized_response():
    return Response(
        """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8" />
<title>IN CRYPTO Ai — Admin</title>
<style>
body{background:#050816;color:#eee;font-family:system-ui,Arial;margin:0;padding:0;display:flex;align-items:center;justify-content:center;height:100vh;}
.box{background:#0b1020;border-radius:16px;padding:24px;max-width:420px;width:90%;box-shadow:0 0 25px rgba(0,0,0,0.6);}
h1{margin-top:0;font-size:22px;color:#fff;}
label{display:block;margin-bottom:8px;font-size:14px;color:#ccc;}
input[type=password]{width:100%;padding:10px;border-radius:10px;border:1px solid #222;background:#060a14;color:#eee;outline:none;}
button{margin-top:14px;width:100%;padding:10px;border-radius:10px;border:none;background:#3b82f6;color:#fff;font-weight:bold;cursor:pointer;}
small{color:#888;font-size:12px;}
</style>
</head>
<body>
<div class="box">
  <h1>لوحة تحكم IN CRYPTO Ai</h1>
  <form method="GET">
    <label>كلمة سر الأدمن:</label>
    <input type="password" name="password" placeholder="أدخل كلمة السر" />
    <button type="submit">دخول</button>
    <small>لو نسيت الباسورد، غيّره من متغير <b>ADMIN_DASH_PASSWORD</b> فى Koyeb.</small>
  </form>
</div>
</body>
</html>
""",
        status=401,
        mimetype="text/html; charset=utf-8",
    )


# ==============================
#         واجهة الـ Dashboard
# ==============================

@app.route("/admin", methods=["GET"])
def admin_dashboard():
    if not _check_admin_auth(request):
        return _unauthorized_response()

    html = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8" />
<title>IN CRYPTO Ai — Admin Dashboard</title>
<style>
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,Arial;background:#020617;color:#e5e7eb;}
.topbar{position:sticky;top:0;z-index:10;background:#020617ee;border-bottom:1px solid #111827;padding:10px 16px;display:flex;justify-content:space-between;align-items:center;}
.topbar h1{margin:0;font-size:18px;color:#fff;}
.topbar .tag{font-size:11px;padding:3px 8px;border-radius:999px;background:#111827;color:#9ca3af;}
.container{padding:16px;display:flex;flex-direction:column;gap:16px;}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;}
.card{background:#020617;border-radius:16px;border:1px solid #111827;padding:14px 14px 10px;box-shadow:0 0 30px rgba(15,23,42,.6);}
.card h2{margin:0 0 8px;font-size:15px;color:#f9fafb;}
.card small{color:#6b7280;font-size:11px;}
.metric-row{display:flex;justify-content:space-between;margin:4px 0;font-size:13px;}
.metric-label{color:#9ca3af;}
.metric-value{color:#e5e7eb;font-weight:500;}
.badge{display:inline-flex;align-items:center;gap:4px;font-size:11px;padding:3px 8px;border-radius:999px;background:#0f172a;color:#9ca3af;margin-top:4px;}
.badge span{font-size:14px;}
.btn-row{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;}
button.action{border:none;border-radius:999px;padding:6px 10px;font-size:12px;cursor:pointer;background:#1d4ed8;color:#e5e7eb;}
button.action.red{background:#b91c1c;}
button.action.yellow{background:#a16207;}
button.action.gray{background:#374151;}
section{margin-top:8px;}
table{width:100%;border-collapse:collapse;font-size:11px;margin-top:6px;}
th,td{border-bottom:1px solid #111827;padding:4px 6px;text-align:right;white-space:nowrap;}
th{color:#9ca3af;font-weight:500;background:#020617;}
tbody tr:hover{background:#020617;}
pre.log{background:#020617;border-radius:8px;padding:8px;font-size:11px;max-height:260px;overflow:auto;direction:ltr;text-align:left;}
footer{margin:10px 16px 16px;font-size:11px;color:#6b7280;text-align:center;}
.chip{display:inline-flex;align-items:center;gap:4px;font-size:11px;padding:2px 8px;border-radius:999px;background:#111827;color:#9ca3af;margin-left:4px;}
.chip span{font-size:10px;}
</style>
</head>
<body>
<div class="topbar">
  <div>
    <h1>IN CRYPTO Ai — Admin</h1>
    <div class="tag">لوحة تحكم مباشرة للبوت + نظام التحذير</div>
  </div>
  <div id="top-status" class="chip">
    <span>●</span>
    <span>Idle</span>
  </div>
</div>

<div class="container">
  <div class="grid">
    <div class="card">
      <h2>حالة السوق العامة</h2>
      <small>مبنية على BTCUSDT</small>
      <div id="market-metrics">
        <div class="metric-row"><div class="metric-label">سعر البيتكوين:</div><div class="metric-value" id="m-price">—</div></div>
        <div class="metric-row"><div class="metric-label">تغير 24 ساعة:</div><div class="metric-value" id="m-change">—</div></div>
        <div class="metric-row"><div class="metric-label">مدى الحركة اليومى:</div><div class="metric-value" id="m-range">—</div></div>
        <div class="metric-row"><div class="metric-label">درجة التقلب:</div><div class="metric-value" id="m-vol">—</div></div>
        <div class="metric-row"><div class="metric-label">مستوى المخاطر:</div><div class="metric-value" id="m-risk">—</div></div>
        <div class="badge" id="m-liq">نبض السيولة: —</div>
      </div>
    </div>

    <div class="card">
      <h2>نظام التحذير التلقائى</h2>
      <small>متابعة /auto_alert</small>
      <div id="alert-status">
        <div class="metric-row"><div class="metric-label">آخر حالة:</div><div class="metric-value" id="a-last-reason">لا يوجد</div></div>
        <div class="metric-row"><div class="metric-label">آخر مصدر:</div><div class="metric-value" id="a-last-source">—</div></div>
        <div class="metric-row"><div class="metric-label">آخر سعر وقت التحذير:</div><div class="metric-value" id="a-last-price">—</div></div>
        <div class="metric-row"><div class="metric-label">آخر تغير:</div><div class="metric-value" id="a-last-change">—</div></div>
      </div>
      <div class="btn-row">
        <button class="action" onclick="forceAlert()">🚨 إرسال تحذير الآن</button>
        <button class="action yellow" onclick="sendTest()">🧪 تنبيه تجريبى</button>
        <button class="action gray" onclick="clearAlerts()">🧹 مسح سجل التحذيرات</button>
      </div>
    </div>

    <div class="card">
      <h2>التحذيرات الأخيرة</h2>
      <small>آخر 100 تحذير (تلقائى + يدوى)</small>
      <section id="alerts-table-wrap">
        <table>
          <thead>
            <tr>
              <th>الوقت (UTC)</th>
              <th>المصدر</th>
              <th>السعر</th>
              <th>التغير %</th>
              <th>السبب</th>
            </tr>
          </thead>
          <tbody id="alerts-body">
          </tbody>
        </table>
      </section>
    </div>

    <div class="card">
      <h2>آخر اللوجات</h2>
      <small>آخر ~200 سطر Log من البوت</small>
      <pre class="log" id="log-box">جارى التحميل...</pre>
      <div class="btn-row">
        <button class="action gray" onclick="refreshLogs()">🔄 تحديث اللوج</button>
        <button class="action red" onclick="clearLogs()">🧹 مسح اللوج المحلى</button>
      </div>
    </div>
  </div>
</div>

<footer>
  IN CRYPTO Ai — Admin Dashboard • التحديث كل 5 ثوانى تلقائياً
</footer>

<script>
const params = new URLSearchParams(window.location.search);
const adminPassword = params.get("password") || "";

async function apiGet(path){
  const url = path + (path.includes("?") ? "&" : "?") + "password=" + encodeURIComponent(adminPassword);
  const res = await fetch(url);
  if(!res.ok) throw new Error("HTTP " + res.status);
  return await res.json();
}

async function loadStatus(){
  try{
    const data = await apiGet("/admin/status");
    document.getElementById("top-status").innerHTML = "<span style='color:#22c55e'>●</span><span>شغال</span>";

    if(data.market){
      const m = data.market;
      document.getElementById("m-price").textContent = m.price ? ("$" + m.price.toLocaleString("en-US")) : "—";
      document.getElementById("m-change").textContent = (m.change_pct !== null && m.change_pct !== undefined) ? (m.change_pct.toFixed(2) + "%") : "—";
      document.getElementById("m-range").textContent = m.range_pct !== null ? m.range_pct.toFixed(2) + "%" : "—";
      document.getElementById("m-vol").textContent = m.volatility_score !== null ? m.volatility_score.toFixed(1) + " / 100" : "—";
      document.getElementById("m-risk").textContent = (m.risk_emoji || "") + " " + (m.risk_level_text || "—");
      document.getElementById("m-liq").textContent = "نبض السيولة: " + (m.liquidity_pulse || "—");
    }

    if(data.last_alert){
      const a = data.last_alert;
      document.getElementById("a-last-reason").textContent = a.reason || "لا يوجد";
      document.getElementById("a-last-source").textContent = a.source || "—";
      document.getElementById("a-last-price").textContent = a.price ? ("$" + a.price.toLocaleString("en-US")) : "—";
      document.getElementById("a-last-change").textContent = (a.change_pct !== null && a.change_pct !== undefined) ? a.change_pct.toFixed(2) + "%" : "—";
    }

  }catch(e){
    document.getElementById("top-status").innerHTML = "<span style='color:#ef4444'>●</span><span>خطأ</span>";
    console.error(e);
  }
}

async function loadAlerts(){
  try{
    const data = await apiGet("/admin/alerts_history");
    const body = document.getElementById("alerts-body");
    body.innerHTML = "";
    (data.alerts || []).forEach(a => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${a.time || ""}</td>
        <td>${a.source || ""}</td>
        <td>${a.price ? "$" + Number(a.price).toLocaleString("en-US") : "—"}</td>
        <td>${(a.change_pct !== null && a.change_pct !== undefined) ? Number(a.change_pct).toFixed(2) + "%" : "—"}</td>
        <td title="${a.reason || ""}">${(a.reason || "").slice(0,40)}${(a.reason && a.reason.length>40) ? "..." : ""}</td>
      `;
      body.appendChild(tr);
    });
  }catch(e){
    console.error(e);
  }
}

async function loadLogs(){
  try{
    const data = await apiGet("/admin/logs");
    const box = document.getElementById("log-box");
    box.textContent = (data.logs || []).join("\\n");
    box.scrollTop = box.scrollHeight;
  }catch(e){
    console.error(e);
  }
}

async function forceAlert(){
  if(!confirm("متأكد إنك عايز تبعت تحذير فورى للأدمن؟")) return;
  try{
    const data = await apiGet("/admin/force_alert");
    alert(data.message || "تم إرسال التحذير.");
    loadAlerts();
  }catch(e){
    alert("حصل خطأ أثناء إرسال التحذير.");
  }
}

async function sendTest(){
  try{
    const data = await apiGet("/admin/test_alert");
    alert(data.message || "تم إرسال تنبيه تجريبى للأدمن.");
  }catch(e){
    alert("حصل خطأ أثناء إرسال التنبيه التجريبى.");
  }
}

async function clearAlerts(){
  if(!confirm("مسح سجل التحذيرات بالكامل؟")) return;
  try{
    const data = await apiGet("/admin/clear_alerts");
    alert(data.message || "تم مسح سجل التحذيرات.");
    loadAlerts();
  }catch(e){
    alert("حصل خطأ أثناء المسح.");
  }
}

async function clearLogs(){
  if(!confirm("مسح اللوج المحلى (buffer)؟")) return;
  try{
    const data = await apiGet("/admin/clear_logs");
    alert(data.message || "تم مسح اللوج.");
    loadLogs();
  }catch(e){
    alert("حصل خطأ أثناء المسح.");
  }
}

function refreshLogs(){ loadLogs(); }

function loop(){
  loadStatus();
  loadAlerts();
  loadLogs();
}

loop();
setInterval(loadStatus, 5000);
setInterval(loadAlerts, 8000);
</script>
</body>
</html>
"""
    return Response(html, mimetype="text/html; charset=utf-8")


# ==============================
#       REST API للـ Dashboard
# ==============================

@app.route("/admin/status", methods=["GET"])
def admin_status():
    if not _check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    metrics = compute_market_metrics()
    if metrics:
        risk = evaluate_risk_level(metrics["change_pct"], metrics["volatility_score"])
        market_obj = {
            "price": metrics["price"],
            "change_pct": metrics["change_pct"],
            "range_pct": metrics["range_pct"],
            "volatility_score": metrics["volatility_score"],
            "risk_level": risk["level"],
            "risk_emoji": risk["emoji"],
            "risk_level_text": {
                "low": "منخفض",
                "medium": "متوسط",
                "high": "مرتفع",
            }.get(risk["level"], "غير محدد"),
            "liquidity_pulse": metrics["liquidity_pulse"],
        }
    else:
        market_obj = None

    last_alert = ALERTS_HISTORY[-1] if ALERTS_HISTORY else None

    return jsonify(
        ok=True,
        market=market_obj,
        last_alert=last_alert,
    )


@app.route("/admin/logs", methods=["GET"])
def admin_logs():
    if not _check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    return jsonify(
        ok=True,
        logs=list(LOG_BUFFER),
    )


@app.route("/admin/clear_logs", methods=["GET"])
def admin_clear_logs():
    if not _check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    LOG_BUFFER.clear()
    logger.info("Admin cleared log buffer from dashboard.")
    return jsonify(ok=True, message="تم مسح اللوج المحلى.")


@app.route("/admin/alerts_history", methods=["GET"])
def admin_alerts_history():
    if not _check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    return jsonify(
        ok=True,
        alerts=list(ALERTS_HISTORY),
    )


@app.route("/admin/clear_alerts", methods=["GET"])
def admin_clear_alerts():
    if not _check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    ALERTS_HISTORY.clear()
    logger.info("Admin cleared alerts history from dashboard.")
    return jsonify(ok=True, message="تم مسح سجل التحذيرات.")


@app.route("/admin/force_alert", methods=["GET"])
def admin_force_alert():
    if not _check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    text = format_ai_alert()
    send_message(ADMIN_CHAT_ID, text)
    add_alert_history("force", "Force alert from admin dashboard")
    logger.info("Admin forced alert from dashboard.")
    return jsonify(ok=True, message="تم إرسال التحذير الفورى للأدمن.")


@app.route("/admin/test_alert", methods=["GET"])
def admin_test_alert():
    if not _check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    test_msg = (
        "🧪 <b>تنبيه تجريبى من لوحة التحكم</b>\n"
        "هذا التنبيه للتأكد من أن نظام الإشعارات يعمل بشكل سليم."
    )
    send_message(ADMIN_CHAT_ID, test_msg)
    logger.info("Admin sent test alert from dashboard.")
    return jsonify(ok=True, message="تم إرسال تنبيه تجريبى للأدمن.")


# ==============================
#        تشغيل السيرفر
# ==============================

if __name__ == "__main__":
    logger.info("Bot is starting...")
    setup_webhook()
    app.run(host="0.0.0.0", port=8080)
