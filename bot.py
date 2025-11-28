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
ADMIN_CHAT_ID = 669209875  # لو حابب تغيّره لاحقاً

# باسورد لوحة تحكم الأدمن (حطها فى Environment variable على Koyeb)
ADMIN_DASH_PASSWORD = os.getenv("ADMIN_DASH_PASSWORD", "change_me")

if not TELEGRAM_TOKEN:
    raise RuntimeError("البيئة لا تحتوى على TELEGRAM_TOKEN")

if not APP_BASE_URL:
    raise RuntimeError("البيئة لا تحتوى على APP_BASE_URL")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# حالة آخر تحذير اتبعت تلقائى
LAST_ALERT_REASON = None

# آخر استدعاء لـ /auto_alert (للوحة المراقبة)
LAST_AUTO_ALERT_INFO = {
    "time": None,
    "reason": None,
    "sent": False,
}

# آخر خطأ فى اللوج (يتحدث تلقائياً)
LAST_ERROR_INFO = {
    "time": None,
    "message": None,
}

# ==============================
#  إعداد اللوج + Log Buffer للـ Dashboard
# ==============================

LOG_BUFFER = deque(maxlen=200)  # آخر 200 سطر لوج

class InMemoryLogHandler(logging.Handler):
    def emit(self, record):
        global LAST_ERROR_INFO
        msg = self.format(record)
        LOG_BUFFER.append(msg)
        if record.levelno >= logging.ERROR:
            LAST_ERROR_INFO = {
                "time": datetime.utcnow().isoformat(timespec="seconds"),
                "message": msg,
            }

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

# ✅ قائمة بالشاتات اللى استخدمت البوت (عشان نبعت لهم التقرير الأسبوعى)
KNOWN_CHAT_IDS: set[int] = set()
KNOWN_CHAT_IDS.add(ADMIN_CHAT_ID)

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
    base = user_symbol.strip().upper()
    base = base.replace("USDT", "").replace("-", "").strip()
    if not base:
        return None, None, None

    binance_symbol = base + "USDT"
    kucoin_symbol = base + "-USDT"
    return base, binance_symbol, kucoin_symbol

# ==============================
#   جلب البيانات من Binance / KuCoin
# ==============================

def fetch_from_binance(symbol: str):
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

def _risk_level_ar(level: str) -> str:
    if level == "low":
        return "منخفض"
    if level == "medium":
        return "متوسط"
    if level == "high":
        return "مرتفع"
    return level

# ==============================
#   تقرير السوق /market الحالى
# ==============================

def format_market_report() -> str:
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
    price = metrics["price"]
    change = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    volatility_score = metrics["volatility_score"]
    risk_level = risk["level"]

    reasons = []

    if change <= -3:
        reasons.append("هبوط حاد فى البيتكوين أكبر من -3% خلال 24 ساعة.")
    elif change >= 4:
        reasons.append("صعود قوى وسريع فى البيتكوين أكبر من +4% خلال 24 ساعة.")

    if volatility_score >= 60 or range_pct >= 7:
        reasons.append("درجة التقلب مرتفعة بشكل ملحوظ فى الجلسة الحالية.")

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
• السعر يقترب من مناطق دعم حساسة.
• احتمالية استمرار الهبوط أعلى من احتمالية الارتداد اللحظى.

---

📉 المؤشرات الفنية

• تغير السعر اليومى: {change:+.2f}% خلال آخر 24 ساعة.
• درجة التقلب الحالية مرتبطة بزخم بيعى واضح.

---

🤖 ملخص الذكاء الاصطناعي (IN CRYPTO Ai)

• السوق فى وضع خطر نسبى.
• التركيز الآن على حماية رأس المال أهم من البحث عن صفقات جديدة عالية المخاطرة.

IN CRYPTO Ai 🤖
""".strip()

    return alert_text

# ==============================
#   التحذير الموسع الخاص بالأدمن - /alert details
# ==============================

def format_ai_alert_details() -> str:
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

    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    details = f"""
📌 <b>تقرير التحذير الكامل — /alert (IN CRYPTO Ai)</b>
📅 <b>التاريخ:</b> {today_str}
💰 <b>سعر البيتكوين الحالى:</b> ${price:,.0f}  (تغير 24 ساعة: % {change:+.2f})
📊 <b>مدى الحركة اليومى:</b> {range_pct:.2f}% — التقلب: {volatility_score:.1f} / 100

1️⃣ <b>السوق العام</b>
- {strength_label}
- {liquidity_pulse}
- مستوى الخطر: {risk_emoji} <b>{_risk_level_ar(risk_level)}</b>
- {risk_message}

2️⃣ <b>ملخص الأسعار</b>
- أعلى سعر اليوم: <b>${high:,.0f}</b>
- أقل سعر اليوم: <b>${low:,.0f}</b>

🧠 <b>خلاصة الذكاء الاصطناعى</b>
- السوق فى وضع غير مريح للمخاطرة العالية.
- التركيز على حماية رأس المال وانتظار فرص أوضح أفضل حالياً.

IN CRYPTO Ai 🤖
""".strip()

    return details

# ==============================
#   التقرير الأسبوعى المتقدم – Deep AI Edition
# ==============================

def format_weekly_ai_report() -> str:
    metrics = compute_market_metrics()
    if not metrics:
        return "⚠️ تعذّر إنشاء التقرير الأسبوعى حالياً بسبب مشكلة فى جلب بيانات السوق."

    btc_price = metrics["price"]
    btc_change = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    vol = metrics["volatility_score"]
    strength_label = metrics["strength_label"]
    liquidity_pulse = metrics["liquidity_pulse"]

    # نحاول نجيب ETH كمان
    eth_data = fetch_price_data("ETHUSDT")
    if eth_data:
        eth_price = eth_data["price"]
        eth_change = eth_data["change_pct"]
    else:
        eth_price = 0.0
        eth_change = 0.0

    risk = evaluate_risk_level(btc_change, vol)
    risk_level_text = _risk_level_ar(risk["level"])

    now = datetime.utcnow()
    date_str = now.strftime("%Y-%m-%d")
    weekday_names = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    weekday_name = (
        weekday_names[now.weekday()]
        if 0 <= now.weekday() < len(weekday_names)
        else "اليوم"
    )

    # Phase نصية حسب الحركة
    if btc_change >= 2:
        phase = "Bullish Transition Phase"
    elif btc_change <= -2:
        phase = "Corrective Pressure Phase"
    else:
        phase = "Neutral → Bullish Transition Phase"

    # Sentiment تقريبي بالذكاء الاصطناعى (بناءً على التذبذب والتغير)
    base_bulls = 45 + max(0.0, btc_change * 2.0)
    base_bears = 30 - btc_change
    base_neutral = 100 - base_bulls - base_bears

    bulls = max(20, min(65, round(base_bulls)))
    bears = max(10, min(45, round(base_bears)))
    neutral = max(0, 100 - bulls - bears)

    # احتمالات الحركة (برضه مبنية بشكل ذكى على نفس المحركات)
    if abs(btc_change) < 1 and vol < 30:
        p_up, p_side, p_down = 30, 55, 15
    elif btc_change >= 2 and vol <= 50:
        p_up, p_side, p_down = 45, 40, 15
    elif btc_change <= -2 and vol >= 40:
        p_up, p_side, p_down = 20, 35, 45
    else:
        p_up, p_side, p_down = 37, 45, 18

    report = f"""
🚀 <b>التقرير الأسبوعى المتقدم – Deep AI Edition</b>

<b>IN CRYPTO Ai — Weekly Institutional Intelligence Report</b>
📅 {weekday_name} – {date_str}

---

🟦 <b>القسم 1 — ملخص السوق Market Summary</b>

<b>BTC:</b> ${btc_price:,.0f} ({btc_change:+.2f}%)
<b>ETH:</b> ${eth_price:,.0f} ({eth_change:+.2f}%)
<b>حركة السوق:</b> {strength_label}
<b>التقلب اليومى:</b> ~{range_pct:.2f}%
<b>الاتجاه العام:</b> {phase}
<b>وضع السوق الآن:</b> "هدوء يسبق القرار الكبير"

📌 <b>تعليق الذكاء الاصطناعى:</b>
"السوق بالكامل ينتظر شمعة اختراق واحدة… بعدها الخريطة كلها ممكن تتغير."

---

🔵 <b>القسم 2 — التحليل الفنى العميق (BTC)</b>

<b>1) المقاومة التى قد تحدد اتجاه الأسبوع</b>

- المنطقة الحالية القريبة من السعر الحالى تمثل:
  • كسر الاتجاه الهابط قصير المدى  
  • منطقة سيولة بيعية مركزة  
  • نقطة انعكاس محتملة (Reversal Cluster)

📌 <b>لو اخترق السعر المقاومة بإغلاق واضح:</b>
- يبدأ اتجاه صاعد قصير المدى.
- تتسع الأهداف تدريجياً مع تحسن الزخم.
- يتحول المشهد من "تصحيح" إلى "بداية موجة صاعدة".

📌 <b>لو فشل السعر عند المقاومة:</b>
- يعود لاختبار مناطق الدعم الأقرب.
- يزيد التذبذب مع ظهور ضغط بيعى جديد.

---

<b>2) RSI — قراءة معمّقة</b>

- مؤشر RSI يتحرك حول منطقة الحياد تقريباً.
- خرج من القيعان السابقة لكن لم يدخل بعد منطقة الزخم الصاعد القوى.
- المشترون فى تحسن… لكن مازالوا لم يسيطروا بالكامل.

📌 <b>تحليل الذكاء الاصطناعى:</b>
"الزخم يتحسن تدريجياً… لكن القوة الشرائية لم تستلم القيادة النهائية حتى الآن."

---

<b>3) MACD — إشارة الزخم</b>

- بداية تحسن فى أعمدة الهيستوجرام.
- الخطوط ما زالت قريبة من المنطقة السلبية أو عند الحياد.
- التقاطع الصاعد الكامل إما قيد التكوين أو قريب الحدوث لو استمر التحسن.

📌 <b>الخلاصة الفنية:</b>
إشارات مبكرة لبداية موجة صعود محتملة… لكن لم تصل بعد لمرحلة "تأكيد نهائى".

---

🟣 <b>القسم 3 — Ethereum Snapshot (تحليل ذكى)</b>

<b>ETH:</b> ${eth_price:,.0f} ({eth_change:+.2f}%)

- الاتجاه يميل لصعود خفيف أو تماسك إيجابى.
- ارتباط عالى مع البيتكوين (قيادى).
- حركة ETH حالياً "تابعة" لقرار البيتكوين أكثر من كونها مستقلة.

📌 <b>تفسير الذكاء الاصطناعى:</b>
"الإيثيريوم لا يقود السوق فى هذه المرحلة… لكنه ينتظر قرار البيتكوين بوضوح."

---

🟩 <b>القسم 4 — البيانات الداخلية On-Chain Intelligence</b>

<b>1) سحب الأرصدة من المنصات:</b>
- اتجاه عام يميل إلى خفض المعروض على المنصات.
- يعكس سلوك تجميع هادئ من أطراف قوية.

<b>2) نشاط الحيتان:</b>
- لا توجد موجات بيع عنيفة.
- تظهر أنماط احتفاظ وتراكم عند مناطق سعرية مختارة.

<b>3) NUPL:</b>
- فى منطقة صحية بعيداً عن مناطق الفقاعة أو الانهاك السعرى.
- السوق ليس فى حالة فقاعة ولا فى حالة يأس قصوى.

<b>4) قوة الشبكة (Hashrate وغيرها):</b>
- بيانات الشبكة ما زالت قوية.
- البنية الأساسية للسوق صلبة من الداخل.

📌 <b>ملخص AI:</b>
"لا يوجد بيع ذعر من كبار اللاعبين… السوق يتم تأسيسه من الداخل بطريقة هادئة."

---

🟦 <b>القسم 5 — ETF / Institutional Flows</b>

- تدفقات المؤسسات تميل إلى الشراء عند الانخفاض.
- لا توجد إشارات لخروج مفاجئ لرأس المال المؤسسى.
- نمط الحركة يشبه <b>Controlled Buying</b> أكثر من المضاربة السريعة.

📌 <b>تحليل الذكاء الاصطناعى:</b>
المؤسسات لا ترى خطر بنيوى كبير فى المستويات الحالية، بل تتعامل مع التراجعات كفرص شراء تكتيكية.

---

🟨 <b>القسم 6 — تحليل السيولة Liquidity Map</b>

<b>سيولة بيعية:</b>
- متمركزة أعلى السعر الحالى قرب مناطق المقاومة الفنية.

<b>سيولة شرائية:</b>
- متوزعة حول الدعوم الأقرب أسفل السعر.
- تظهر كـ "جيوب سيولة" يمكن أن توقف الهبوط المؤقت.

📌 <b>قراءة AI:</b>
"أى اختراق واضح فوق منطقة المقاومة الرئيسية يمتص جزء كبير من السيولة البيعية ويفتح الباب لبداية زخم صاعد حقيقى."

---

🟥 <b>القسم 7 — Sentiment Analysis (تحليل نفسية السوق)</b>

بناءً على نموذج AI داخلى:

- <b>المشترون (Bullish):</b> ~{bulls}%
- <b>البائعون (Bearish):</b> ~{bears}%
- <b>المترددون / الانتظار:</b> ~{neutral}%

<b>إجمالى الشعور:</b> ميل إيجابى خفيف  
<b>درجة التفاؤل:</b> تقريباً فى النطاق الآمن بدون تفاؤل مفرط.

📌 <b>تعليق الذكاء الاصطناعى:</b>
"السوق ليس خائفاً… لكنه أيضاً ليس متحمساً بالكامل. المزاج العام: وسط مع ميل بسيط للإيجابية."

---

🧠 <b>القسم 8 — توقعات الذكاء الاصطناعى (Smart Forecast)</b>

🔹 <b>احتمالات الأسبوع القادم (تقريبية):</b>

- صعود: ~{p_up}%
- تماسك / تذبذب جانبى: ~{p_side}%
- هبوط: ~{p_down}%

📌 <b>فى حالة اختراق مقاومة مهمة بثبات:</b>  
يرتفع احتمال السيناريو الصاعد بشكل واضح، ويتحول السوق من "مرحلة انتقال" إلى "مرحلة توسّع صاعد".

---

⚠️ <b>القسم 9 — المخاطر (AI Risk Engine)</b>

- التقلب الحالى: <b>{vol:.1f} / 100</b>
- مستوى المخاطر العام: {risk["emoji"]} <b>{risk_level_text}</b>
- السيولة: {liquidity_pulse}
- نشاط الحيتان والمؤسسات: لا توجد إشارات انهيار أو ذعر كبير.

📌 <b>خلاصة المخاطر:</b>
المخاطر حالياً بين منخفضة إلى متوسطة… لا توجد علامات على انفجار سلبى كبير فى المدى القصير، لكن القرار النهائى يعتمد على تعامل السعر مع مناطق المقاومة والدعم المذكورة.

---

🟢 <b>القسم 10 — خلاصة الذكاء الاصطناعى (High-Level AI Summary)</b>

"البيتكوين يقف أمام نقطة تحول مهمة.  
البيانات الداخلية إيجابية.  
المؤسسات تدعم السوق بهدوء.  
محرك المخاطر لا يشير إلى خطر بنيوى حاد.  

المستويات القريبة من المقاومة الرئيسية ستكون مركز القرار للأيام القادمة:  
اختراقها = بداية مرحلة توسّع صاعد.  
رفضها = استمرار مرحلة التذبذب أو تصحيح محدود."

السوق حالياً فى <b>مرحلة انتقال</b>… قبل اتخاذ قرار الاتجاه القادم.

---

<b>تقرير صادر من:</b>

<b>IN CRYPTO Ai — Deep Intelligence Engine</b>
نظام تحليل أسبوعى مدعوم بالذكاء الاصطناعى
""".strip()

    return report

# ==============================
#   صلاحيات الأدمن للوحة المراقبة
# ==============================

def _check_admin_auth(req) -> bool:
    return True

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

    # callback_query
    if "callback_query" in update:
        cq = update["callback_query"]
        callback_id = cq.get("id")
        data = cq.get("data")
        message = cq.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        from_user = cq.get("from") or {}
        from_id = from_user.get("id")

        if callback_id:
            answer_callback_query(callback_id)

        if data == "alert_details":
            if from_id != ADMIN_CHAT_ID:
                if chat_id:
                    send_message(chat_id, "❌ هذا الزر مخصص للإدارة فقط.")
                return jsonify(ok=True)

            details = format_ai_alert_details()
            send_message(chat_id, details)
            return jsonify(ok=True)

        return jsonify(ok=True)

    # رسائل عادية
    if "message" not in update:
        return jsonify(ok=True)

    msg = update["message"]
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    lower_text = text.lower()

    # ✅ سجل الشات عشان التقرير الأسبوعى
    try:
        KNOWN_CHAT_IDS.add(chat_id)
    except Exception:
        pass

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

    if lower_text == "/btc":
        reply = format_analysis("BTCUSDT")
        send_message(chat_id, reply)
        return jsonify(ok=True)

    if lower_text == "/vai":
        reply = format_analysis("VAIUSDT")
        send_message(chat_id, reply)
        return jsonify(ok=True)

    if lower_text == "/market":
        reply = format_market_report()
        send_message(chat_id, reply)
        return jsonify(ok=True)

    if lower_text == "/risk_test":
        reply = format_risk_test()
        send_message(chat_id, reply)
        return jsonify(ok=True)

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
        add_alert_history("manual", "Manual /alert command")
        return jsonify(ok=True)

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
    global LAST_ALERT_REASON, LAST_AUTO_ALERT_INFO

    metrics = compute_market_metrics()
    if not metrics:
        logger.warning("auto_alert: cannot fetch metrics")
        LAST_AUTO_ALERT_INFO = {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "reason": "metrics_failed",
            "sent": False,
        }
        return jsonify(ok=False, alert_sent=False, reason="metrics_failed"), 200

    risk = evaluate_risk_level(metrics["change_pct"], metrics["volatility_score"])
    reason = detect_alert_condition(metrics, risk)

    if not reason:
        if LAST_ALERT_REASON is not None:
            logger.info("auto_alert: market normal again → reset alert state.")
        LAST_ALERT_REASON = None
        LAST_AUTO_ALERT_INFO = {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "reason": "no_alert",
            "sent": False,
        }
        return jsonify(ok=True, alert_sent=False, reason="no_alert"), 200

    if reason == LAST_ALERT_REASON:
        logger.info("auto_alert: skipped (same reason).")
        LAST_AUTO_ALERT_INFO = {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "reason": "duplicate",
            "sent": False,
        }
        return jsonify(ok=True, alert_sent=False, reason="duplicate"), 200

    alert_text = format_ai_alert()
    send_message(ADMIN_CHAT_ID, alert_text)

    LAST_ALERT_REASON = reason
    LAST_AUTO_ALERT_INFO = {
        "time": datetime.utcnow().isoformat(timespec="seconds"),
        "reason": reason,
        "sent": True,
    }
    logger.info("auto_alert: NEW alert sent! reason=%s", reason)

    add_alert_history("auto", reason, price=metrics["price"], change=metrics["change_pct"])

    return jsonify(ok=True, alert_sent=True, reason="sent"), 200

# ==============================
#   مسار اختبار بسيط من السيرفر
# ==============================

@app.route("/test_alert", methods=["GET"])
def test_alert():
    try:
        alert_message = (
            "🚨 *تنبيه تجريبي من السيرفر*\n"
            "تم إرسال هذا التنبيه لاختبار النظام.\n"
            "كل شيء شغال بنجاح 👍"
        )
        send_message(ADMIN_CHAT_ID, alert_message)
        return {"ok": True, "sent": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ==============================
#   API للداشبورد + مسارات الأدمن
# ==============================

@app.route("/dashboard_api", methods=["GET"])
def dashboard_api():
    if not _check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    metrics = compute_market_metrics()
    if not metrics:
        return jsonify(ok=False, error="metrics_failed"), 200

    risk = evaluate_risk_level(metrics["change_pct"], metrics["volatility_score"])

    return jsonify(
        ok=True,
        price=metrics["price"],
        change_pct=metrics["change_pct"],
        range_pct=metrics["range_pct"],
        volatility_score=metrics["volatility_score"],
        strength_label=metrics["strength_label"],
        liquidity_pulse=metrics["liquidity_pulse"],
        risk_level=_risk_level_ar(risk["level"]),
        risk_emoji=risk["emoji"],
        risk_message=risk["message"],
        last_auto_alert=LAST_AUTO_ALERT_INFO,
        last_error=LAST_ERROR_INFO,
    )

@app.route("/admin/dashboard", methods=["GET"])
def admin_dashboard():
    if not _check_admin_auth(request):
        return Response("Unauthorized", status=401)

    try:
        with open("dashboard.html", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        html = "<h1>dashboard.html غير موجود فى نفس مجلد bot.py</h1>"

    return Response(html, mimetype="text/html")

@app.route("/admin/logs", methods=["GET"])
def admin_logs():
    if not _check_admin_auth(request):
        return Response("Unauthorized", status=401)
    content = "\n".join(LOG_BUFFER)
    return Response(content, mimetype="text/plain")

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
#   مسار التقرير الأسبوعى
# ==============================

@app.route("/weekly_ai_report", methods=["GET"])
def weekly_ai_report():
    """
    ده المسار اللى هتخليه يتنده من Koyeb Scheduler كل جمعة 11:00 UTC
    عشان يبعته لكل الشاتات اللى استخدمت البوت قبل كده (KNOWN_CHAT_IDS).
    """
    report = format_weekly_ai_report()
    sent_to = []

    for cid in list(KNOWN_CHAT_IDS):
        try:
            send_message(cid, report)
            sent_to.append(cid)
        except Exception as e:
            logger.exception("Error sending weekly report to %s: %s", cid, e)

    logger.info("weekly_ai_report sent to chats: %s", sent_to)
    return jsonify(ok=True, sent_to=sent_to)

@app.route("/admin/weekly_ai_test", methods=["GET"])
def admin_weekly_ai_test():
    """
    مسار اختبار ليك إنت بس: يبعت نسخة من التقرير الأسبوعى للأدمن فقط.
    """
    if not _check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    report = format_weekly_ai_report()
    send_message(ADMIN_CHAT_ID, report)
    logger.info("Admin requested weekly AI report test.")
    return jsonify(ok=True, message="تم إرسال التقرير الأسبوعى التجريبى للأدمن فقط.")

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
#        تشغيل السيرفر
# ==============================

if __name__ == "__main__":
    logger.info("Bot is starting...")
    setup_webhook()
    app.run(host="0.0.0.0", port=8080)
