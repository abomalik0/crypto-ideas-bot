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

# تجميع كل المستخدمين اللى استخدموا البوت (للتقرير الأسبوعى)
USERS = set()

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
#   تسجيل المستخدمين (للتقرير الأسبوعى)
# ==============================

def register_user(chat_id: int):
    """إضافة المستخدم لقائمة متلقى التقرير الأسبوعى."""
    try:
        USERS.add(chat_id)
    except Exception as e:
        logger.exception("Error while registering user: %s", e)

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
#   تقرير أسبوعى Premium AI
# ==============================

def format_weekly_report() -> str:
    """
    تقرير أسبوعى للسوق بأسلوب احترافى مبنى على:
    - سعر البيتكوين الحالى
    - نسبة التغير اليومية (كمؤشر لحالة الأسبوع)
    - التقلب
    - قوة الاتجاه
    - نبض السيولة
    - محرك المخاطر
    """
    metrics = compute_market_metrics()
    if not metrics:
        return (
            "⚠️ تعذّر إعداد التقرير الأسبوعى لأن بيانات السوق غير متاحة الآن.\n"
            "حاول لاحقًا."
        )

    price = metrics["price"]
    change = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    volatility_score = metrics["volatility_score"]
    strength_label = metrics["strength_label"]
    liquidity_pulse = metrics["liquidity_pulse"]

    risk = evaluate_risk_level(change, volatility_score)

    today = datetime.utcnow()
    date_str = today.strftime("%Y-%m-%d")

    # توصيف الحالة العامة من منظور أسبوعى
    if change >= 4:
        weekly_trend = "أسبوع يميل إلى الصعود القوي مع شهية مخاطرة مرتفعة نسبيًا."
    elif change >= 1:
        weekly_trend = "أسبوع إيجابى بملامح صعود تدريجى بدون اندفاع مبالغ فيه."
    elif change > -1:
        weekly_trend = "أسبوع متذبذب أقرب للحياد، السوق يبحث عن اتجاه واضح."
    elif change > -4:
        weekly_trend = "أسبوع يميل للتصحيح الهابط لكن بدون حالة ذعر قوية."
    else:
        weekly_trend = "أسبوع سلبى واضح يطغى عليه ضغط بيعى حاد وتخفيف مراكز."

    if volatility_score >= 60:
        vol_comment = "السوق مرّ بحالة تقلبات عالية، الحركة السعريّة سريعة والتذبذب واضح."
    elif volatility_score >= 30:
        vol_comment = "التقلبات متوسطة، والسوق يسمح بفرص مضاربية مع ضرورة ضبط أحجام العقود."
    else:
        vol_comment = "التقلبات محدودة نسبيًا، الحركة أكثر هدوءًا وتميل للتجميع أو الاستراحة."

    risk_level_ar = _risk_level_ar(risk["level"])

    report = f"""
📍 <b>التقرير الأسبوعى لسوق الكريبتو</b>
📅 أسبوع منتهى فى: <b>{date_str}</b>

💰 <b>سعر البيتكوين وقت إعداد التقرير:</b> <b>${price:,.0f}</b>
📉 <b>تغير آخر 24 ساعة (كصورة عن نهاية الأسبوع):</b> <b>%{change:+.2f}</b>

---

🔵 <b>أولاً: قراءة الحالة العامة – Weekly Market Context</b>

- {weekly_trend}
- {strength_label}
- {vol_comment}

مدى حركة السعر خلال اليوم الأخير بالنسبة للمستوى الحالى حوالى: <b>{range_pct:.2f}%</b>،
وهو ما يعكس مدى اتساع النطاق السعري الذى يتحرك فيه السوق فى نهاية هذا الأسبوع.

---

🟣 <b>ثانيًا: السيولة واتجاه المال الذكى</b>

- <b>نبض السيولة (Liquidity Pulse):</b>
  {liquidity_pulse}

بمعنى آخر:
إذا كانت السيولة تميل للدخول، فالأسواق عادةً تهيّئ أرضية لبناء مراكز على المدى المتوسط.
أما إذا كانت السيولة خارجة بوضوح، فالأولوية القصوى هى حماية رأس المال لا مطاردة الفرص.

---

🟡 <b>ثالثًا: محرك المخاطر (Risk Engine)</b>

- مستوى المخاطر الحالى: {risk['emoji']} <b>{risk_level_ar}</b>
- توصيف النظام:
  {risk['message']}

هذا التقييم لا يُعتبر حكم نهائى على اتجاه السوق،
بل هو “مقياس حرارة” يخبرك:

- متى يكون فتح صفقات جديدة منطقيًا
- ومتى يكون الأفضل تهدئة التعامل أو الاكتفاء بإدارة المراكز المفتوحة

---

🧭 <b>رابعًا: نظرة تكتيكية للأسبوع القادم</b>

1) <b>للمضارب اليومى / قصير الأجل:</b>
- فى فترات التقلب العالى، الأفضل تقليل حجم العقود والاعتماد على أهداف قريبة ووقف خسارة صارم.
- فى فترات الهدوء والتجميع، التركيز يكون على مناطق الانعكاس الواضحة بدل مطاردة الحركة العشوائية.

2) <b>للمستثمر متوسط المدى:</b>
- راقب سلوك السعر حول الدعوم والمقاومات الرئيسية بدل التركيز على شمعة واحدة أو يوم واحد.
- وجود تقلبات مرتفعة مع سيولة خارجة = احتمال استمرار التصحيح.
- وجود تقلبات مع سيولة داخلة = إعادة تجميع وفرص لبناء مراكز تدريجية بحذر.

---

🧠 <b>خلاصة الذكاء الاصطناعى (IN CRYPTO Ai)</b>

بعد دمج:
- حركة السعر
- التقلب
- نبض السيولة
- محرك المخاطر

يُقدّر النظام أن:

- <b>المهمة الأساسية</b> خلال الأسبوع القادم:
  هى <b>ضبط إدارة المخاطر</b> قبل التفكير فى تعظيم الأرباح.
- <b>أفضل أسلوب حاليًا:</b>
  - عدم مطاردة كل حركة صغيرة
  - انتظار مناطق سعرية أوضح ليتم بناء القرارات حولها
  - الحفاظ على مرونة عالية فى اتخاذ قرار الخروج قبل الدخول فى أى مركز كبير

فى النهاية:
السوق دائمًا يفتح فرصًا جديدة،
لكن رأس المال إذا فُقد لا يعود بسهولة.

IN CRYPTO Ai 🤖
""".strip()

    return report

# ==============================
#   صلاحيات الأدمن للوحة المراقبة
# ==============================

def _check_admin_auth(req) -> bool:
    # حاليًا مفتوحة — لو حبيت تقفلها لاحقًا ممكن تربط بـ ADMIN_DASH_PASSWORD
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

    # تسجيل المستخدم للتقرير الأسبوعى
    register_user(chat_id)

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
            "• <code>/alert</code> — تحذير كامل (للأدمن فقط)\n"
            "• <code>/weekly_me</code> — تقرير أسبوعى تجريبى (للأدمن فقط)\n\n"
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

    # تقرير أسبوعى تجريبى — للأدمن فقط
    if lower_text == "/weekly_me":
        if chat_id != ADMIN_CHAT_ID:
            send_message(chat_id, "❌ هذا الأمر مخصص للإدارة فقط.")
            return jsonify(ok=True)
        weekly = format_weekly_report()
        send_message(chat_id, weekly)
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
#   مسارات الداشبورد /admin و /dashboard_api
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
#   مسار التقرير الأسبوعى للإرسال الجماعى
# ==============================

@app.route("/weekly_report", methods=["GET"])
def weekly_report():
    """
    يُستدعى من CRON على Koyeb كل يوم جمعة الساعة 11:00 صباحًا بتوقيت UTC
    (اللى هى 1 ظهرًا بتوقيت مصر تقريبًا).
    يرسل التقرير الأسبوعى لكل المستخدمين المسجلين فى USERS.
    """
    if not USERS:
        logger.info("weekly_report: no users registered yet.")
        return jsonify(ok=True, sent=0, users=0, note="no_users"), 200

    text = format_weekly_report()
    sent = 0
    for uid in list(USERS):
        try:
            send_message(uid, text)
            sent += 1
        except Exception as e:
            logger.exception("weekly_report: error sending to %s: %s", uid, e)

    logger.info("weekly_report: sent weekly report to %d users.", sent)
    return jsonify(ok=True, sent=sent, users=len(USERS)), 200

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
