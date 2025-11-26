import os
import logging
import requests
from datetime import datetime, date
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
    """إرسال رسالة عادية إلى تليجرام."""
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
                "Telegram sendMessage error: %s - %s", r.status_code, r.text
            )
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

    binance_symbol = base + "USDT"  # مثال: BTC → BTCUSDT
    kucoin_symbol = base + "-USDT"  # مثال: BTC → BTC-USDT

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
#     صياغة رسالة التحليل للعملات
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
            "وحاول مرة أخرى."
        )

    price = data["price"]
    change = data["change_pct"]
    high = data["high"]
    low = data["low"]
    exchange = data["exchange"]  # binance / kucoin

    base, binance_symbol, kucoin_symbol = normalize_symbol(user_symbol)
    display_symbol = (binance_symbol if exchange == "binance" else kucoin_symbol).replace(
        "-", ""
    )

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


# ===========================================
#    CoinGecko – بيانات السوق العامة (Market)
# ===========================================

COINGECKO_BASE = "https://api.coingecko.com/api/v3"


def fetch_global_market_data():
    """
    يجلب بيانات السوق العامة من CoinGecko:
    - إجمالى القيمة السوقية
    - نسب هيمنة البيتكوين والإيثريوم
    - نسبة التغير فى إجمالى السوق آخر 24 ساعة
    """
    try:
        url = f"{COINGECKO_BASE}/global"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            logger.warning("CoinGecko global error: %s - %s", r.status_code, r.text)
            return None

        j = r.json().get("data") or {}
        total_mc = float((j.get("total_market_cap") or {}).get("usd") or 0.0)
        market_cap_percentage = j.get("market_cap_percentage") or {}
        btc_dom = float(market_cap_percentage.get("btc") or 0.0)
        eth_dom = float(market_cap_percentage.get("eth") or 0.0)
        total_change_24h = float(j.get("market_cap_change_percentage_24h_usd") or 0.0)

        if total_mc <= 0:
            return None

        return {
            "total_market_cap": total_mc,
            "btc_dominance": btc_dom,
            "eth_dominance": eth_dom,
            "total_change_24h": total_change_24h,
        }
    except Exception as e:
        logger.exception("Error fetching CoinGecko global: %s", e)
        return None


def fetch_btc_eth_data():
    """
    يجلب سعر البيتكوين والإيثريوم + تغير 24 ساعة من CoinGecko.
    """
    try:
        url = f"{COINGECKO_BASE}/simple/price"
        params = {
            "ids": "bitcoin,ethereum",
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        }
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            logger.warning("CoinGecko price error: %s - %s", r.status_code, r.text)
            return None

        j = r.json()
        btc = j.get("bitcoin") or {}
        eth = j.get("ethereum") or {}

        btc_price = float(btc.get("usd") or 0.0)
        btc_change = float(btc.get("usd_24h_change") or 0.0)
        eth_price = float(eth.get("usd") or 0.0)
        eth_change = float(eth.get("usd_24h_change") or 0.0)

        if btc_price <= 0 or eth_price <= 0:
            return None

        return {
            "btc_price": btc_price,
            "btc_change_24h": btc_change,
            "eth_price": eth_price,
            "eth_change_24h": eth_change,
        }
    except Exception as e:
        logger.exception("Error fetching CoinGecko BTC/ETH: %s", e)
        return None


def human_format_cap(value: float):
    """
    تحويل القيمة السوقية لصيغة بشرية:
    - T ترليون
    - B مليار
    """
    if value >= 1e12:
        return f"${value/1e12:,.2f}T"
    return f"${value/1e9:,.2f}B"


def build_market_snapshot():
    """
    يبنى Snapshot كامل للسوق من CoinGecko.
    يرجع dict أو None.
    """
    global_data = fetch_global_market_data()
    btc_eth = fetch_btc_eth_data()

    if not global_data or not btc_eth:
        return None

    total_cap = global_data["total_market_cap"]
    btc_dom = global_data["btc_dominance"]
    eth_dom = global_data["eth_dominance"]
    total_change = global_data["total_change_24h"]

    # تقدير القيمة السوقية للبيتكوين و الإيثريوم من الهيمنة
    btc_cap = total_cap * (btc_dom / 100.0)
    eth_cap = total_cap * (eth_dom / 100.0)
    alt_cap = max(total_cap - btc_cap - eth_cap, 0.0)

    alt_cap_str = human_format_cap(alt_cap)
    total_cap_str = human_format_cap(total_cap)

    btc_price = btc_eth["btc_price"]
    btc_change = btc_eth["btc_change_24h"]
    eth_price = btc_eth["eth_price"]
    eth_change = btc_eth["eth_change_24h"]

    # اتجاه البيتكوين
    if btc_change > 2:
        btc_trend = "صعودى قوى"
    elif btc_change > 0:
        btc_trend = "صعودى"
    elif btc_change > -2:
        btc_trend = "متذبذب مع هبوط خفيف"
    else:
        btc_trend = "هابط بوضوح"

    # اتجاه السوق الكلى
    if total_change > 2:
        market_trend = "السوق يميل إلى الصعود مع تحسن فى السيولة."
    elif total_change > 0:
        market_trend = "السوق يميل إلى الصعود الخفيف مع استقرار نسبى."
    elif total_change > -2:
        market_trend = "السوق متذبذب مع ميل بسيط للهبوط."
    else:
        market_trend = "السوق يميل إلى الهبوط مع خروج جزء من السيولة."

    snapshot = {
        "date": date.today().isoformat(),
        "btc_price": btc_price,
        "btc_change": btc_change,
        "btc_trend": btc_trend,
        "eth_price": eth_price,
        "eth_change": eth_change,
        "total_cap": total_cap,
        "total_cap_str": total_cap_str,
        "alt_cap": alt_cap,
        "alt_cap_str": alt_cap_str,
        "btc_dom": btc_dom,
        "eth_dom": eth_dom,
        "total_change": total_change,
        "market_trend": market_trend,
    }

    return snapshot


# ==============================
#   نظام تقييم المخاطر (Balanced)
# ==============================


def evaluate_risk_level(snapshot: dict):
    """
    نظام بسيط لتقييم المخاطر (حساسية متوازنة A-Level).
    يعتمد على:
    - تغير BTC 24h
    - تغير إجمالى السوق 24h
    - هيمنة البيتكوين
    يرجع:
    - risk_level: 'low' / 'medium' / 'high'
    - risk_emoji: 🟢 / 🟡 / 🔴
    - risk_message: شرح قصير
    """

    btc_change = snapshot["btc_change"]
    total_change = snapshot["total_change"]
    btc_dom = snapshot["btc_dom"]

    # نشتق درجة من 0 إلى 100 تقريبياً
    score = 60.0

    # تأثير تغير البيتكوين
    if btc_change >= 5:
        score += 10
    elif btc_change >= 2:
        score += 5
    elif btc_change <= -5:
        score -= 15
    elif btc_change <= -2:
        score -= 8

    # تأثير تغير إجمالى السوق
    if total_change >= 4:
        score += 8
    elif total_change >= 1:
        score += 3
    elif total_change <= -4:
        score -= 10
    elif total_change <= -1:
        score -= 5

    # تأثير هيمنة البيتكوين (ارتفاع الهيمنة = ضغط على العملات البديلة)
    if btc_dom >= 60:
        score -= 10
    elif btc_dom >= 57:
        score -= 5
    elif btc_dom <= 50 and total_change > 0:
        score += 4

    # حدود السكور
    score = max(0, min(100, score))

    if score >= 65:
        risk_level = "low"
        risk_emoji = "🟢"
        risk_msg = (
            "المخاطر حالياً تبدو منخفضة نسبيًا مع تحسن فى حركة السوق، "
            "لكن يفضّل دائمًا الحفاظ على إدارة مخاطر منضبطة."
        )
    elif score >= 45:
        risk_level = "medium"
        risk_emoji = "🟡"
        risk_msg = (
            "المخاطر حالياً متوسطة؛ السوق فى حالة تذبذب بين المشترين والبائعين، "
            "ويُفضّل الدخول بمخاطرة محسوبة وتقليل الرافعة المالية."
        )
    else:
        risk_level = "high"
        risk_emoji = "🔴"
        risk_msg = (
            "المخاطر حالياً مرتفعة؛ حركة السوق غير مستقرة مع احتمالات هبوط أو تصحيح "
            "أكبر، يُفضّل الحذر الشديد وتقليل حجم الصفقات."
        )

    return risk_level, risk_emoji, risk_msg


# ==============================
#     صياغة تقرير /market
# ==============================


def format_market_report(snapshot: dict) -> str:
    """
    يبنى تقرير سوق احترافى بناءً على Snapshot من CoinGecko.
    """

    (
        risk_level,
        risk_emoji,
        risk_message,
    ) = evaluate_risk_level(snapshot)

    date_str = snapshot["date"]
    btc_price = snapshot["btc_price"]
    btc_change = snapshot["btc_change"]
    btc_trend = snapshot["btc_trend"]
    total_cap_str = snapshot["total_cap_str"]
    alt_cap_str = snapshot["alt_cap_str"]
    btc_dom = snapshot["btc_dom"]
    eth_dom = snapshot["eth_dom"]
    total_change = snapshot["total_change"]
    market_trend = snapshot["market_trend"]

    # تفسير لفظى للمستوى
    if risk_level == "low":
        risk_level_ar = "منخفض"
    elif risk_level == "medium":
        risk_level_ar = "متوسط"
    else:
        risk_level_ar = "مرتفع"

    report = f"""
✅ <b>تحليل الذكاء الاصطناعى لسوق الكريبتو</b>
📅 <b>التاريخ:</b> {date_str}

🏛️ <b>نظرة عامة على البيتكوين:</b>
- السعر الحالى للبيتكوين: <b>${btc_price:,.0f}</b>
- نسبة تغير آخر 24 ساعة: <b>{btc_change:+.2f}%</b> → {btc_trend}

🌍 <b>نظرة عامة على سيولة العملات البديلة (تقريبًا Total3):</b>
- القيمة التقديرية لسوق العملات البديلة: <b>{alt_cap_str}</b>
- القيمة التقديرية لإجمالى السوق: <b>{total_cap_str}</b>
- التغير الإجمالى فى إجمالى السيولة آخر 24 ساعة: <b>{total_change:+.2f}%</b>

📊 <b>هيمنة السوق:</b>
- هيمنة البيتكوين: <b>{btc_dom:.2f}%</b>
- هيمنة الإيثيريوم: <b>{eth_dom:.2f}%</b>

💎 <b>تقييم الوضع العام:</b>
- {market_trend}
- أى تحسن واضح فى السيولة الداخلة للسوق مع صعود متماسك فى البيتكوين يعطى إشارات أفضل للتداول المضاربى.

⚙️ <b>مستوى المخاطر (نظام التحذير الذكى):</b>
- المخاطر حاليًا عند مستوى: {risk_emoji} <b>{risk_level_ar}</b>
- {risk_message}

📈 <b>التوقعات القادمة (وفق البيانات الحالية فقط):</b>
- استمرار تماسك البيتكوين أعلى مناطق الدعم الرئيسية يدعم فرص الاستقرار وتحسن السيولة.
- كسر مناطق الدعم الهامة مع هبوط واضح فى Total3 قد يشير لموجة ضغط جديدة على العملات البديلة.

📌 <b>الملخص النهائى:</b>
- السوق حاليًا يتابع حركة البيتكوين والسيولة الداخلة والخارجة من العملات البديلة.
- يُفضّل التركيز على المناطق الواضحة للدعم والمقاومة مع عدم المبالغة فى الرافعة المالية.

⚠️ <b>رسالة اليوم من IN CRYPTO Ai:</b>
- لا تحاول مطاردة كل حركة؛ ركّز على الفرص الواضحة فقط واعتبر إدارة المخاطر جزءًا من استراتيجية الربح لا عائقًا لها.
- الصبر فى أوقات الضبابية يكون أفضل من الدخول المتأخر فى حركة قوية.

IN CRYPTO Ai 🤖
""".strip()

    return report


# ==============================
#     تقرير مختصر /risk_test
# ==============================


def format_risk_test(snapshot: dict) -> str:
    risk_level, risk_emoji, risk_message = evaluate_risk_level(snapshot)

    if risk_level == "low":
        risk_level_ar = "منخفض"
    elif risk_level == "medium":
        risk_level_ar = "متوسط"
    else:
        risk_level_ar = "مرتفع"

    text = f"""
⚙️ <b>اختبار سريع لمستوى المخاطر فى السوق</b>

- مستوى المخاطر الحالى: {risk_emoji} <b>{risk_level_ar}</b>
- {risk_message}

📊 يعتمد هذا التقييم على بيانات سوقية مباشرة من CoinGecko
(إجمالى القيمة السوقية، تغير 24 ساعة، وهيمنة البيتكوين والإيثيريوم).
""".strip()

    return text


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
            "تقرير السوق العام:\n"
            "➤ <code>/market</code> لتحليل سوق الكريبتو بالكامل.\n"
            "➤ <code>/risk_test</code> لاختبار مستوى المخاطر الحالى.\n\n"
            "البوت يحاول أولاً جلب البيانات من Binance، "
            "وإذا لم يجد العملة يحاول تلقائياً من KuCoin، "
            "و بيانات السوق العامة يتم جلبها من CoinGecko."
        )
        send_message(chat_id, welcome)
        return jsonify(ok=True)

    # /btc
    if lower_text == "/btc":
        reply = format_analysis("BTCUSDT")
        send_message(chat_id, reply)
        return jsonify(ok=True)

    # /vai  (VAI → KuCoin تلقائياً لو مش موجودة فى Binance)
    if lower_text == "/vai":
        reply = format_analysis("VAIUSDT")
        send_message(chat_id, reply)
        return jsonify(ok=True)

    # /market – تقرير السوق العام
    if lower_text == "/market":
        snapshot = build_market_snapshot()
        if not snapshot:
            send_message(
                chat_id,
                "⚠️ لا يمكن جلب بيانات السوق العامة الآن.\n"
                "جرّب لاحقًا، قد يكون هناك ضغط أو حد على CoinGecko.",
            )
        else:
            report = format_market_report(snapshot)
            send_message(chat_id, report)
        return jsonify(ok=True)

    # /risk_test – اختبار سريع للمخاطر
    if lower_text == "/risk_test":
        snapshot = build_market_snapshot()
        if not snapshot:
            send_message(
                chat_id,
                "⚠️ لا يمكن جلب بيانات السوق الآن لاختبار المخاطر.\n"
                "حاول مرة أخرى بعد قليل.",
            )
        else:
            txt = format_risk_test(snapshot)
            send_message(chat_id, txt)
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
        "مثال سريع: <code>/btc</code> أو <code>/coin btc</code> أو <code>/market</code>.",
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
