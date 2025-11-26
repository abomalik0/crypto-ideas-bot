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
COINGECKO_API = "https://api.coingecko.com/api/v3"

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
        url = f"https://api.binance.com/api/v3/ticker/24hr"
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

def format_price(value: float, decimals_if_small: int = 6) -> str:
    """تنسيق سعر/قيمة بشكل مقروء."""
    try:
        v = float(value)
    except Exception:
        return str(value)

    if v >= 1000:
        # أرقام كبيرة → بدون كسور مع فواصل
        return f"{v:,.0f}"
    elif v >= 1:
        return f"{v:.3f}".rstrip("0").rstrip(".")
    else:
        return f"{v:.{decimals_if_small}f}".rstrip("0").rstrip(".")


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
    # exchange = data["exchange"]  # مش هنستخدمه فى الرسالة عشان شيلنا حتة مصدر البيانات

    base, binance_symbol, kucoin_symbol = normalize_symbol(user_symbol)
    display_symbol = (binance_symbol if data["exchange"] == "binance" else kucoin_symbol).replace("-", "")

    # مستويات دعم / مقاومة بسيطة (تجريبية)
    support = low * 0.99 if low > 0 else price * 0.95
    resistance = high * 1.01 if high > 0 else price * 1.05

    # RSI تجريبى مبنى على نسبة التغير
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

💰 <b>السعر الحالى:</b> {format_price(price)}
📉 <b>تغير اليوم:</b> %{change:.2f}

🎯 <b>حركة السعر العامة:</b>
- {trend_text}

📍 <b>مستويات فنية مهمة:</b>
- دعم يومى تقريبى حول: <b>{format_price(support)}</b>
- مقاومة يومية تقريبية حول: <b>{format_price(resistance)}</b>

📉 <b>RSI (تجريبى):</b>
- مؤشر القوة النسبية عند حوالى: <b>{rsi:.1f}</b> → {rsi_trend}

{ai_note}
""".strip()

    return msg


# ==============================
#   دوال CoinGecko للسوق العام
# ==============================

def fetch_global_market_data():
    """
    جلب بيانات السوق العامة من CoinGecko:
    - إجمالى ماركت كاب
    - إجمالى حجم التداول
    - نسبة هيمنة BTC/ETH
    - نسبة تغير ماركت كاب خلال 24h
    """
    url = f"{COINGECKO_API}/global"
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        logger.info("CoinGecko /global error: %s - %s", r.status_code, r.text)
        return None

    j = r.json().get("data") or {}
    total_mcap_usd = float((j.get("total_market_cap") or {}).get("usd") or 0.0)
    total_volume_usd = float((j.get("total_volume") or {}).get("usd") or 0.0)
    mcap_change_pct_24h = float(j.get("market_cap_change_percentage_24h_usd") or 0.0)
    mcap_pct = j.get("market_cap_percentage") or {}
    btc_dom = float(mcap_pct.get("btc") or 0.0)
    eth_dom = float(mcap_pct.get("eth") or 0.0)

    return {
        "total_mcap_usd": total_mcap_usd,
        "total_volume_usd": total_volume_usd,
        "mcap_change_pct_24h": mcap_change_pct_24h,
        "btc_dom": btc_dom,
        "eth_dom": eth_dom,
    }


def fetch_btc_eth_data():
    """
    جلب بيانات BTC و ETH من CoinGecko:
    - السعر الحالى
    - نسبة التغير 24 ساعة
    - الماركت كاب
    """
    url = f"{COINGECKO_API}/coins/markets"
    params = {
        "vs_currency": "usd",
        "ids": "bitcoin,ethereum",
        "price_change_percentage": "24h",
    }
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        logger.info("CoinGecko /coins/markets error: %s - %s", r.status_code, r.text)
        return None

    arr = r.json()
    result = {}
    for item in arr:
        cid = item.get("id")
        if cid not in ("bitcoin", "ethereum"):
            continue
        result[cid] = {
            "price": float(item.get("current_price") or 0.0),
            "mcap": float(item.get("market_cap") or 0.0),
            "change_pct_24h": float(item.get("price_change_percentage_24h") or 0.0),
        }

    if "bitcoin" not in result or "ethereum" not in result:
        return None
    return result


def build_market_snapshot():
    """
    يبنى Snapshot للسوق:
    - سعر BTC + نسبة التغير
    - هيمنة BTC/ETH
    - Total Market Cap
    - AltCap (تقريباً = السوق - BTC - ETH)
    - Alt Dominance
    """
    global_data = fetch_global_market_data()
    if not global_data:
        return None

    btc_eth = fetch_btc_eth_data()
    if not btc_eth:
        return None

    total_mcap_usd = global_data["total_mcap_usd"]
    total_volume_usd = global_data["total_volume_usd"]
    mcap_change_pct_24h = global_data["mcap_change_pct_24h"]
    btc_dom = global_data["btc_dom"]
    eth_dom = global_data["eth_dom"]

    btc = btc_eth["bitcoin"]
    eth = btc_eth["ethereum"]

    btc_price = btc["price"]
    btc_change_pct = btc["change_pct_24h"]
    btc_mcap = btc["mcap"]
    eth_mcap = eth["mcap"]
    eth_change_pct = eth["change_pct_24h"]

    # AltCap = إجمالى السوق - BTC - ETH (لو المعطيات منطقية)
    altcap_usd = total_mcap_usd - btc_mcap - eth_mcap
    if altcap_usd < 0:
        altcap_usd = max(0.0, total_mcap_usd * max(0.0, 1.0 - (btc_dom + eth_dom) / 100.0))

    alt_dominance = max(0.0, 100.0 - btc_dom - eth_dom)

    snapshot = {
        "total_mcap_usd": total_mcap_usd,
        "total_volume_usd": total_volume_usd,
        "mcap_change_pct_24h": mcap_change_pct_24h,
        "btc_price": btc_price,
        "btc_change_pct": btc_change_pct,
        "btc_dom": btc_dom,
        "btc_mcap": btc_mcap,
        "eth_price": eth["price"],
        "eth_change_pct": eth_change_pct,
        "eth_dom": eth_dom,
        "eth_mcap": eth_mcap,
        "altcap_usd": altcap_usd,
        "alt_dominance": alt_dominance,
    }
    return snapshot


# ==============================
#   نظام تقييم المخاطر للسوق
# ==============================

def evaluate_risk_level(snapshot):
    """
    نظام بسيط لتقييم المخاطر (حساسية Balanced):
    يرجّع:
    - risk_level: low / medium / high
    - risk_emoji: 🟢 / 🟡 / 🔴
    - risk_message: جملة توضيحية
    """
    btc_ch = snapshot["btc_change_pct"]
    mcap_ch = snapshot["mcap_change_pct_24h"]
    btc_dom = snapshot["btc_dom"]
    eth_dom = snapshot["eth_dom"]
    alt_dom = snapshot["alt_dominance"]

    reasons = []

    # شروط مخاطر عالية
    high = False
    if btc_ch <= -4:
        high = True
        reasons.append("هبوط يومى قوى فى البيتكوين.")
    if mcap_ch <= -3:
        high = True
        reasons.append("انخفاض واضح فى إجمالى قيمة السوق.")
    if btc_dom >= 55 and btc_ch < 0:
        high = True
        reasons.append("هيمنة بيتكوين مرتفعة مع ضغط بيعى على السوق.")
    if alt_dom <= 30:
        high = True
        reasons.append("سيولة ضعيفة نسبيًا فى العملات البديلة.")

    if high:
        return (
            "high",
            "🔴",
            "السوق فى حالة مخاطر مرتفعة نسبيًا، يُفضَّل تخفيف المراكز ومراقبة الحركة بحذر.",
            reasons,
        )

    # مخاطر متوسطة
    medium = False
    if -4 < btc_ch <= -1:
        medium = True
        reasons.append("تصحيح طبيعى فى البيتكوين لكن مع ضغط ملحوظ.")
    if -3 < mcap_ch <= -1:
        medium = True
        reasons.append("انخفاض متوسط فى قيمة السوق.")
    if 50 <= btc_dom < 55:
        medium = True
        reasons.append("هيمنة بيتكوين تقترب من مستويات تضغط على العملات البديلة.")

    if medium:
        return (
            "medium",
            "🟡",
            "مستوى مخاطر متوسط؛ السوق متذبذب ويحتاج إدارة رأس مال منضبطة.",
            reasons,
        )

    # مخاطر منخفضة
    reasons.append("حركة السوق الحالية متوازنة نسبيًا بدون إشارات خطر قوية.")
    return (
        "low",
        "🟢",
        "مستوى المخاطر حاليًا منخفض إلى متوازن، مع إمكانية بناء مراكز بحذر.",
        reasons,
    )


# ==============================
#   تقرير /market الاحترافى
# ==============================

def format_billion(x: float) -> str:
    """تحويل رقم كبير إلى B مثل 894.5B."""
    try:
        v = float(x)
    except Exception:
        return str(x)
    return f"{v / 1_000_000_000:.1f}B"


def format_market_report(snapshot) -> str:
    today = datetime.utcnow().strftime("%Y-%m-%d")

    total_mcap_b = format_billion(snapshot["total_mcap_usd"])
    altcap_b = format_billion(snapshot["altcap_usd"])
    total_volume_b = format_billion(snapshot["total_volume_usd"])

    btc_price = snapshot["btc_price"]
    btc_ch = snapshot["btc_change_pct"]
    btc_dom = snapshot["btc_dom"]
    eth_dom = snapshot["eth_dom"]
    eth_price = snapshot["eth_price"]
    eth_ch = snapshot["eth_change_pct"]
    alt_dom = snapshot["alt_dominance"]
    mcap_ch = snapshot["mcap_change_pct_24h"]

    risk_level, risk_emoji, risk_msg, reasons = evaluate_risk_level(snapshot)

    reasons_text = ""
    if reasons:
        reasons_text = "\n".join(f"- {r}" for r in reasons)

    text = f"""
🧭 <b>تحليل الذكاء الاصطناعى لسوق العملات الرقمية</b> – {today}

🏦 <b>نظرة عامة على السوق:</b>
- إجمالى القيمة السوقية (Total Market Cap): <b>{total_mcap_b} دولار</b>
- سيولة العملات البديلة (تقريبًا Total3): <b>{altcap_b} دولار</b>
- حجم التداول اليومى (24h Volume): <b>{total_volume_b} دولار</b>
- التغير اليومى فى إجمالى السوق: <b>{mcap_ch:.2f}%</b>

💰 <b>البيتكوين (BTC):</b>
- السعر الحالى: <b>{format_price(btc_price)}</b>$
- تغير 24 ساعة: <b>{btc_ch:.2f}%</b>
- هيمنة السوق (BTC Dominance): <b>{btc_dom:.2f}%</b>

🪙 <b>الإيثريوم (ETH):</b>
- السعر الحالى: <b>{format_price(eth_price)}</b>$
- تغير 24 ساعة: <b>{eth_ch:.2f}%</b>
- هيمنة الإيثريوم: <b>{eth_dom:.2f}%</b>

📊 <b>سيولة العملات البديلة:</b>
- هيمنة تقريبية لباقى السوق (Alt Dominance): <b>{alt_dom:.2f}%</b>
- كلما انخفضت هذه النسبة مع ارتفاع هيمنة البيتكوين، زادت حساسية العملات البديلة لأى هبوط فى BTC.

---

💎 <b>تقييم الوضع العام:</b>

استثماريًا:
- الحفاظ على هيمنة بيتكوين حول <b>{btc_dom:.1f}%</b> مع توازن فى سيولة العملات البديلة
  يعنى أن السوق لم يدخل بعد فى فقاعة مضاربية قوية.
- أى صعود مستمر فى القيمة السوقية الكلية مع بقاء BTC Dominance تحت ~60٪
  يُعتبر بيئة مقبولة لبناء مراكز على مراحل.

مضاربيًا:
- حركة البيتكوين اليومية عند <b>{btc_ch:.2f}%</b> مع تغير إجمالى السوق <b>{mcap_ch:.2f}%</b>
  تعكس درجة تذبذب حالية يجب أخذها فى الحسبان عند استخدام الرافعة المالية.
- العملات البديلة تتأثر سريعاً بأى هبوط مفاجئ فى البيتكوين، خاصة مع هيمنة حاليّة حوالى <b>{btc_dom:.1f}%</b>.

---

⚙️ <b>مستوى المخاطر اليومى:</b>
- المستوى: {risk_emoji} <b>{risk_level.upper()}</b>
- التقييم: {risk_msg}
{(chr(10) + "📌 أسباب مختصرة:\n" + reasons_text) if reasons_text else ""}

---

⚠️ <b>رسالة اليوم من IN CRYPTO Ai:</b>
> الهدف الأساسى هو حماية رأس المال قبل البحث عن الفرص.
> راقب حركة البيتكوين والسيولة فى العملات البديلة، وتجنّب الدخول فى صفقات كبيرة
  قبل تأكيد الاتجاه على الأقل على إطار اليومى.
IN CRYPTO Ai 🤖
""".strip()

    return text


def format_risk_test(snapshot) -> str:
    """
    تقرير قصير لاختبار المخاطر فقط (/risk_test)
    """
    risk_level, risk_emoji, risk_msg, reasons = evaluate_risk_level(snapshot)
    reasons_text = ""
    if reasons:
        reasons_text = "\n".join(f"- {r}" for r in reasons)

    text = f"""
🔍 <b>اختبار مستوى المخاطر اليومى للسوق</b>

- المستوى الحالى: {risk_emoji} <b>{risk_level.upper()}</b>
- التقييم: {risk_msg}

📌 أهم العوامل الملاحظة:
{reasons_text if reasons_text else '- لا توجد إشارات خطر واضحة حالياً.'}
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
            "أوامر التحليل المتاحة:\n"
            "➤ <code>/btc</code> → تحليل البيتكوين.\n"
            "➤ <code>/vai</code> → تحليل VAI (من KuCoin تلقائيًا لو غير متاحة فى Binance).\n"
            "➤ <code>/coin btc</code> أو <code>/coin btcusdt</code> أو أى رمز آخر.\n\n"
            "أوامر السوق العامة:\n"
            "➤ <code>/market</code> → تقرير احترافى عن حالة السوق (هيمنة BTC/ETH + سيولة البدائل).\n"
            "➤ <code>/risk_test</code> → فحص سريع لمستوى المخاطر اليومى.\n\n"
            "البوت يحاول أولاً جلب البيانات من Binance، "
            "وإذا لم يجد العملة يحاول تلقائياً من KuCoin."
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

    # /market → تقرير السوق
    if lower_text == "/market":
        snapshot = build_market_snapshot()
        if not snapshot:
            send_message(
                chat_id,
                "⚠️ تعذّر جلب بيانات السوق العامة من CoinGecko فى الوقت الحالى.\n"
                "جرّب الأمر مرة أخرى بعد قليل."
            )
        else:
            report = format_market_report(snapshot)
            send_message(chat_id, report)
        return jsonify(ok=True)

    # /risk_test → اختبار سريع للمخاطر
    if lower_text == "/risk_test":
        snapshot = build_market_snapshot()
        if not snapshot:
            send_message(
                chat_id,
                "⚠️ تعذّر جلب بيانات السوق العامة من CoinGecko فى الوقت الحالى.\n"
                "جرّب الأمر مرة أخرى بعد قليل."
            )
        else:
            report = format_risk_test(snapshot)
            send_message(chat_id, report)
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
