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
                "Binance error %s for %s: %s", r.status_code, symbol, r.text
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
                "KuCoin error %s for %s: %s", r.status_code, symbol, r.text
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
    فيه دعم VAI من KuCoin تلقائياً.
    """
    data = fetch_price_data(user_symbol)
    if not data:
        return (
            "⚠️ لا يمكن جلب بيانات هذه العملة الآن.\n"
            "تأكد من الرمز (مثال: <code>BTC</code> أو <code>BTCUSDT</code> "
            "أو <code>VAI</code>) وحاول مرة أخرى."
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

    # مستويات دعم / مقاومة بسيطة
    support = round(low * 0.99, 6) if low > 0 else round(price * 0.95, 6)
    resistance = round(high * 1.01, 6) if high > 0 else round(price * 1.05, 6)

    # RSI تقريبى مبنى على نسبة التغير
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


# ===========================================
#   بيانات سوق الكريبتو (CoinStats API)
# ===========================================

COINSTATS_BASE = "https://api.coinstats.app/public/v1"


def fetch_coinstats_global():
    """
    جلب بيانات السوق العامة من CoinStats.
    يرجع dict أو None.
    """
    try:
        url = f"{COINSTATS_BASE}/global"
        r = requests.get(url, params={"currency": "USD"}, timeout=10)
        if r.status_code != 200:
            logger.warning(
                "CoinStats global error %s - %s", r.status_code, r.text
            )
            return None
        return r.json() or {}
    except Exception as e:
        logger.exception("Error fetching CoinStats global: %s", e)
        return None


def fetch_coinstats_coin(coin_id: str):
    """
    جلب بيانات عملة معينة من CoinStats (bitcoin, ethereum, ...).
    """
    try:
        url = f"{COINSTATS_BASE}/coins/{coin_id}"
        r = requests.get(url, params={"currency": "USD"}, timeout=10)
        if r.status_code != 200:
            logger.warning(
                "CoinStats coin %s error %s - %s",
                coin_id,
                r.status_code,
                r.text,
            )
            return None

        data = r.json() or {}
        coins = data.get("coin") or data.get("coins")
        if isinstance(coins, list):
            return coins[0] if coins else None
        return coins
    except Exception as e:
        logger.exception("Error fetching CoinStats coin %s: %s", coin_id, e)
        return None


def build_market_snapshot():
    """
    يبنى Snapshot موحّد لسوق الكريبتو من CoinStats:
    - سعر BTC + تغيير 24 ساعة
    - إجمالى القيمة السوقية
    - هيمنة BTC / ETH صحيحة
    - قيمة سوق العملات البديلة (Total3 تقريباً)
    """
    global_data = fetch_coinstats_global()
    if not global_data:
        return None

    # CoinStats global structure:
    # {
    #   "totalMarketCap": ...,
    #   "total24hVolume": ...,
    #   "btcDominance": ...,
    #   "ethDominance": ...,
    #   ...
    # }
    total_cap = float(global_data.get("totalMarketCap") or 0.0)
    total_volume = float(global_data.get("total24hVolume") or 0.0)
    btc_dom = float(global_data.get("btcDominance") or 0.0)
    eth_dom = float(global_data.get("ethDominance") or 0.0)

    # حساب قيمة سوق BTC / ETH من الهيمنة
    btc_cap = total_cap * btc_dom / 100.0
    eth_cap = total_cap * eth_dom / 100.0
    alt_cap = max(total_cap - btc_cap - eth_cap, 0.0)

    # Total3 تقريبى = قيمة سوق العملات البديلة (Billion)
    total3_b = alt_cap / 1e9

    # بيانات BTC
    btc_data = fetch_coinstats_coin("bitcoin")
    if not btc_data:
        return None

    btc_price = float(btc_data.get("price") or 0.0)
    # CoinStats: priceChange1d = نسبة التغير خلال 24 ساعة (بالنسبة المئوية)
    btc_change_24h = float(btc_data.get("priceChange1d") or 0.0)

    snapshot = {
        "total_cap": total_cap,
        "total_volume": total_volume,
        "btc_dom": btc_dom,
        "eth_dom": eth_dom,
        "alt_cap": alt_cap,
        "total3_b": total3_b,
        "btc_price": btc_price,
        "btc_change_24h": btc_change_24h,
    }

    return snapshot


# ===========================================
#   نظام تقييم المخاطر (Risk Engine)
# ===========================================

def evaluate_risk_level(snapshot):
    """
    يحسب مستوى المخاطر من:
    - تغير BTC خلال 24 ساعة
    - هيمنة البيتكوين
    - حجم سوق العملات البديلة
    يرجع:
    - risk_level: low / medium / high
    - risk_emoji
    - risk_message (عربى)
    """
    btc_change = snapshot["btc_change_24h"]
    btc_dom = snapshot["btc_dom"]
    total3_b = snapshot["total3_b"]

    score = 50.0

    # زخم البيتكوين
    if btc_change <= -5:
        score -= 25
    elif btc_change <= -2:
        score -= 15
    elif btc_change >= 5:
        score += 15
    elif btc_change >= 2:
        score += 8

    # هيمنة البيتكوين
    if btc_dom >= 60:
        score -= 15
    elif btc_dom >= 57:
        score -= 8
    elif btc_dom <= 50:
        score += 5

    # حجم سوق العملات البديلة
    if total3_b < 300:
        score -= 10
    elif total3_b > 900:
        score += 5

    # قصّ الدرجة
    score = max(0, min(100, score))

    if score >= 65:
        level = "low"   # مخاطر منخفضة
    elif score >= 40:
        level = "medium"
    else:
        level = "high"

    if level == "low":
        emoji = "🟢"
        msg = (
            "المخاطر حالياً تبدو منخفضة نسبيًا مع تحسن تدريجى "
            "فى السيولة واستقرار نسبى فى حركة البيتكوين."
        )
    elif level == "medium":
        emoji = "🟡"
        msg = (
            "المخاطر حالياً متوسطة؛ السوق فى حالة تذبذب، "
            "ويفضّل الدخول بمراكز صغيرة مع إدارة مخاطر واضحة."
        )
    else:
        emoji = "🔴"
        msg = (
            "المخاطر حالياً مرتفعة؛ ضغط بيعى أو هيمنة قوية للبيتكوين "
            "مع ضعف فى العملات البديلة. يُفضّل الحذر الشديد وتقليل الرافعة."
        )

    return {
        "risk_score": score,
        "risk_level": level,
        "risk_emoji": emoji,
        "risk_message": msg,
    }


# ===========================================
#   تقرير السوق /market
# ===========================================

def format_market_report():
    snapshot = build_market_snapshot()
    if not snapshot:
        return (
            "⚠️ تعذّر جلب بيانات السوق العامة حاليًا من المزود.\n"
            "حاول مرة أخرى بعد قليل."
        )

    risk = evaluate_risk_level(snapshot)

    today = datetime.utcnow().strftime("%Y-%m-%d")

    btc_price = snapshot["btc_price"]
    btc_change = snapshot["btc_change_24h"]
    btc_dom = snapshot["btc_dom"]
    eth_dom = snapshot["eth_dom"]
    total_cap = snapshot["total_cap"]
    alt_cap = snapshot["alt_cap"]
    total3_b = snapshot["total3_b"]

    # تنسيقات نصية
    total_cap_str = f"{total_cap/1e12:.3f}T$"
    alt_cap_str = f"{alt_cap/1e12:.3f}T$"
    total3_str = f"{total3_b:.1f}B$"

    # اتجاه السوق العام من BTC + Total3
    if btc_change > 3:
        market_trend = (
            "السوق يميل إلى الصعود مع زخم واضح على البيتكوين "
            "وتحسن تدريجى فى العملات البديلة."
        )
    elif btc_change > 0:
        market_trend = (
            "السوق يميل إلى الصعود الهادى؛ البيتكوين إيجابى "
            "لكن ما زال من المهم مراقبة حركة العملات البديلة."
        )
    elif btc_change > -3:
        market_trend = (
            "السوق فى حالة تذبذب مع ميل خفيف للهبوط؛ "
            "يُفضّل تجنب المراكز الكبيرة."
        )
    else:
        market_trend = (
            "السوق يميل إلى الهبوط مع ضغوط بيعية ملحوظة "
            "على البيتكوين وباقى السوق."
        )

    # مستوى المخاطر بالعربى
    if risk["risk_level"] == "low":
        risk_level_ar = "منخفض"
    elif risk["risk_level"] == "medium":
        risk_level_ar = "متوسط"
    else:
        risk_level_ar = "عالٍ"

    risk_emoji = risk["risk_emoji"]
    risk_message = risk["risk_message"]

    report = f"""
✅ <b>تحليل الذكاء الاصطناعى لسوق الكريبتو</b>
📅 <b>التاريخ:</b> {today}

🏛 <b>نظرة عامة على البيتكوين:</b>
- السعر الحالى للبيتكوين: <b>${btc_price:,.0f}</b>
- نسبة تغير آخر 24 ساعة: <b>%{btc_change:+.2f}</b>

🌍 <b>نظرة عامة على سيولة العملات البديلة (Total3 تقريبًا):</b>
- القيمة التقديرية لسوق العملات البديلة: <b>{alt_cap_str}</b>
- إجمالى قيمة السوق الكلية: <b>{total_cap_str}</b>
- قيمة تقريبية لسوق العملات البديلة (Total3): <b>{total3_str}</b>

📊 <b>هيمنة السوق:</b>
- هيمنة البيتكوين: <b>{btc_dom:.2f}%</b>
- هيمنة الإيثريوم: <b>{eth_dom:.2f}%</b>

💎 <b>تقييم الوضع العام:</b>
- {market_trend}

⚙️ <b>مستوى المخاطر (نظام التحذير الذكى):</b>
- المخاطر حاليًا عند مستوى: {risk_emoji} <b>{risk_level_ar}</b>
- {risk_message}

📈 <b>التوقعات القادمة (وفق البيانات الحالية فقط):</b>
- استمرار تحسن البيتكوين أعلى مناطق الدعم الحالية يعزز فرص الاستقرار وتحسن السيولة.
- أى كسر حاد لمناطق الدعم مع ارتفاع هيمنة البيتكوين قد يشير لموجة ضغط جديدة على العملات البديلة.

📌 <b>الملخص النهائى:</b>
- السوق حالياً يتابع حركة البيتكوين والسيولة الداخلة والخارجة من العملات البديلة.
- يُفضّل التركيز على المناطق الواضحة للدعم والمقاومة مع عدم المبالغة فى الرافعة المالية.

⚠️ <b>رسالة اليوم من IN CRYPTO Ai:</b>
- لا تحاول مطاردة كل حركة؛ ركّز على الفرص الواضحة فقط واعتبر إدارة المخاطر جزءًا من استراتيجيتك الربحية لا عائقًا لها.
- فى أوقات المخاطر المرتفعة يكون <b>أفضل من الدخول المتأخر فى حركة قوية.</b>

IN CRYPTO Ai 🤖
""".strip()

    return report


def format_risk_test():
    snapshot = build_market_snapshot()
    if not snapshot:
        return (
            "⚠️ تعذّر جلب بيانات المخاطر حاليًا من المزود.\n"
            "حاول مرة أخرى بعد قليل."
        )

    risk = evaluate_risk_level(snapshot)

    btc_change = snapshot["btc_change_24h"]
    btc_dom = snapshot["btc_dom"]
    total3_b = snapshot["total3_b"]

    if risk["risk_level"] == "low":
        risk_level_ar = "منخفض"
    elif risk["risk_level"] == "medium":
        risk_level_ar = "متوسط"
    else:
        risk_level_ar = "عالٍ"

    msg = f"""
🧪 <b>اختبار سريع لمستوى المخاطر فى السوق</b>

- تغير البيتكوين آخر 24 ساعة: <b>%{btc_change:+.2f}</b>
- هيمنة البيتكوين الحالية: <b>{btc_dom:.2f}%</b>
- حجم تقريبى لسوق العملات البديلة (Total3): <b>{total3_b:.1f}B$</b>

⚙️ <b>تقييم النظام:</b>
- المستوى الحالى للمخاطر: {risk["risk_emoji"]} <b>{risk_level_ar}</b>
- {risk["risk_message"]}

📌 هذا الاختبار يعتمد على بيانات CoinStats العامة لحظيًا.
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
            "كما يمكنك طلب تقرير كامل عن السوق:\n"
            "➤ <code>/market</code>\n"
            "➤ <code>/risk_test</code> لاختبار المخاطر السريع.\n\n"
            "البوت يحاول أولاً جلب البيانات من Binance، "
            "وإذا لم يجد العملة يحاول تلقائياً من KuCoin، "
            "بينما بيانات السوق العامة من CoinStats."
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

    # تقرير السوق /market
    if lower_text == "/market":
        reply = format_market_report()
        send_message(chat_id, reply)
        return jsonify(ok=True)

    # اختبار المخاطر /risk_test
    if lower_text == "/risk_test":
        reply = format_risk_test()
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
        "مثال سريع: <code>/btc</code> أو <code>/coin btc</code> "
        "أو <code>/market</code>.",
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
    app.run(host="0.0.0.0", port=8080)
