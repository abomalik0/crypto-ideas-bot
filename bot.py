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
    display_symbol = (binance_symbol if exchange == "binance" else kucoin_symbol).replace("-", "")

    # مستويات دعم / مقاومة بسيطة (تجريبية)
    support = round(low * 0.99, 6) if low > 0 else round(price * 0.95, 6)
    resistance = round(high * 1.01, 6) if high > 0 else round(price * 1.05, 6)

    # RSI تجريبى مبنى على نسبة التغير
    # (مش RSI حقيقى، لكن يعطى إحساس بالزخم)
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
        # شيلنا ذكر Binance الصريح زى ما طلبت قبل كده
        source_note = ""

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
#         CoinGecko – Market
# ==============================

def fetch_global_market_data():
    """
    جلب بيانات السوق العامة من CoinGecko:
    إجمالى القيمة السوقية + نسب هيمنة BTC و ETH + تغير 24 ساعة.
    """
    try:
        url = f"{COINGECKO_API}/global"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            logger.warning("CoinGecko /global error: %s - %s", r.status_code, r.text)
            return None

        data = r.json().get("data") or {}
        total_cap_usd = float((data.get("total_market_cap") or {}).get("usd") or 0)
        dominance = data.get("market_cap_percentage") or {}
        btc_dom = float(dominance.get("btc") or 0.0)
        eth_dom = float(dominance.get("eth") or 0.0)
        total_change = float(data.get("market_cap_change_percentage_24h_usd") or 0.0)

        return {
            "total_cap_usd": total_cap_usd,
            "btc_dominance": btc_dom,
            "eth_dominance": eth_dom,
            "total_change_pct": total_change,
        }
    except Exception as e:
        logger.exception("Error fetching CoinGecko global data: %s", e)
        return None


def fetch_btc_eth_data():
    """
    جلب سعر البيتكوين + الإيثريوم وتغير 24 ساعة من CoinGecko.
    """
    try:
        url = f"{COINGECKO_API}/simple/price"
        params = {
            "ids": "bitcoin,ethereum",
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        }
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            logger.warning("CoinGecko /simple/price error: %s - %s", r.status_code, r.text)
            return None

        data = r.json()
        btc = data.get("bitcoin") or {}
        eth = data.get("ethereum") or {}

        btc_price = float(btc.get("usd") or 0)
        btc_change = float(btc.get("usd_24h_change") or 0.0)
        eth_price = float(eth.get("usd") or 0)
        eth_change = float(eth.get("usd_24h_change") or 0.0)

        return {
            "btc_price": btc_price,
            "btc_change_pct": btc_change,
            "eth_price": eth_price,
            "eth_change_pct": eth_change,
        }
    except Exception as e:
        logger.exception("Error fetching CoinGecko BTC/ETH data: %s", e)
        return None


def evaluate_risk_level(btc_change, total_change, alt_cap_usd, btc_dom, eth_dom):
    """
    نظام تقييم مخاطر بسيط (حساسية A متوازنة).
    """
    try:
        # قواعد تقريبية:
        # هبوط قوى فى السوق أو البيتكوين → high
        if total_change <= -4 or btc_change <= -5:
            level = "high"
            emoji = "🔴"
            msg = (
                "المخاطر مرتفعة حاليًا؛ السوق يتعرض لضغط بيعى واضح، "
                "ويُفضّل تجنب الدخول الجديد إلا بحساب دقيق لحجم الصفقة."
            )
        # سوق متذبذب / غير واضح → medium
        elif -4 < total_change < 1 and abs(btc_change) < 4:
            level = "medium"
            emoji = "🟡"
            msg = (
                "المخاطر متوسطة؛ السوق يتحرك فى نطاق متقلب مع عدم وضوح اتجاه "
                "قوى، ويُفضّل تقليل الرافعة والالتزام بمناطق دعم ومقاومة واضحة."
            )
        # باقى الحالات → low
        else:
            level = "low"
            emoji = "🟢"
            msg = (
                "المخاطر حالياً منخفضة نسبيًا؛ الحركة العامة متوازنة، "
                "مع إمكانية استغلال الفرص ولكن مع الحفاظ على إدارة رأس مال منضبطة."
            )

        # لو هيمنة BTC عالية جدًا مع AltCap ضعيف → نحذر زيادة شوية
        if alt_cap_usd > 0 and btc_dom > 52 and total_change < 0:
            msg += (
                "\n⚠️ توجد سيطرة ملحوظة للبيتكوين مقارنة بالعملات البديلة، "
                "مما قد يزيد من حدة الهبوط فى بعض العملات الصغيرة."
            )

        return level, emoji, msg
    except Exception as e:
        logger.exception("Error evaluating risk: %s", e)
        return "unknown", "⚪", "تعذر حساب مستوى المخاطر بدقة بسبب مشكلة فى البيانات."


def build_market_snapshot():
    """
    يجمع كل بيانات السوق فى dict واحد لاستخدامه فى التقرير /market
    أو أمر /risk_test.
    """
    global_data = fetch_global_market_data()
    btc_eth_data = fetch_btc_eth_data()

    if not global_data or not btc_eth_data:
        return None

    total_cap = global_data["total_cap_usd"]
    btc_dom = global_data["btc_dominance"]
    eth_dom = global_data["eth_dominance"]
    total_change = global_data["total_change_pct"]

    btc_price = btc_eth_data["btc_price"]
    btc_change = btc_eth_data["btc_change_pct"]
    eth_price = btc_eth_data["eth_price"]
    eth_change = btc_eth_data["eth_change_pct"]

    # نحسب القيمة السوقية التقريبية BTC/ETH من الهيمنة
    btc_cap = total_cap * (btc_dom / 100.0)
    eth_cap = total_cap * (eth_dom / 100.0)
    alt_cap = max(total_cap - btc_cap - eth_cap, 0)

    # تقييم المخاطر
    risk_level, risk_emoji, risk_message = evaluate_risk_level(
        btc_change=btc_change,
        total_change=total_change,
        alt_cap_usd=alt_cap,
        btc_dom=btc_dom,
        eth_dom=eth_dom,
    )

    # نص الاتجاه العام
    if total_change > 2 and btc_change > 2:
        market_trend = (
            "السوق يميل إلى الصعود مع تحسن فى البيتكوين وباقى السوق، "
            "لكن يظل من المهم مراقبة مستويات المقاومة الرئيسية."
        )
    elif total_change < -2 and btc_change < -2:
        market_trend = (
            "السوق يعانى من ضغوط بيعية واضحة، مع هبوط ملحوظ فى القيمة "
            "السوقية العامة وفى البيتكوين."
        )
    else:
        market_trend = (
            "السوق يتحرك داخل نطاق متذبذب بدون اتجاه قوى واضح حتى الآن، "
            "ومناسب أكثر للتداول قصير المدى بحذر."
        )

    today = datetime.utcnow().strftime("%d-%m-%Y")

    snapshot = {
        "date_str": today,
        "btc_price": btc_price,
        "btc_change": btc_change,
        "eth_price": eth_price,
        "eth_change": eth_change,
        "total_cap": total_cap,
        "alt_cap": alt_cap,
        "btc_dom": btc_dom,
        "eth_dom": eth_dom,
        "total_change": total_change,
        "market_trend": market_trend,
        "risk_level": risk_level,
        "risk_emoji": risk_emoji,
        "risk_message": risk_message,
    }
    return snapshot


def format_market_report(snapshot: dict) -> str:
    """
    صياغة تقرير سوق كامل لأمر /market.
    """
    date_str = snapshot["date_str"]
    btc_price = snapshot["btc_price"]
    btc_change = snapshot["btc_change"]
    eth_price = snapshot["eth_price"]
    eth_change = snapshot["eth_change"]
    total_cap = snapshot["total_cap"]
    alt_cap = snapshot["alt_cap"]
    btc_dom = snapshot["btc_dom"]
    eth_dom = snapshot["eth_dom"]
    total_change = snapshot["total_change"]
    market_trend = snapshot["market_trend"]
    risk_level = snapshot["risk_level"]
    risk_emoji = snapshot["risk_emoji"]
    risk_message = snapshot["risk_message"]

    # تحويل الأرقام لسلاسل مفهومة
    total_cap_trillions = total_cap / 1e12
    alt_cap_billions = alt_cap / 1e9

    btc_trend = "⬆️ صعودى" if btc_change > 0 else ("⬇️ هابط" if btc_change < 0 else "🔁 عرضى")
    eth_trend = "⬆️ صعودى" if eth_change > 0 else ("⬇️ هابط" if eth_change < 0 else "🔁 عرضى")
    total_trend = "⬆️ تحسن فى إجمالى القيمة" if total_change > 0 else (
        "⬇️ ضعف فى إجمالى القيمة" if total_change < 0 else "🔁 استقرار نسبى فى إجمالى القيمة"
    )

    # عنوان التقرير – من غير "تصحيح تاريخ التحليل"
    report = f"""
✅ <b>تحليل الذكاء الاصطناعى لسوق الكريبتو</b>
📅 التاريخ: <b>{date_str}</b>

🏛 <b>نظرة عامة على البيتكوين:</b>
- السعر الحالى للبيتكوين: <b>${btc_price:,.0f}</b>
- نسبة تغير آخر 24 ساعة: <b>{btc_change:+.2f}%</b> → {btc_trend}

🪙 <b>نظرة عامة على سيولة العملات البديلة (Total3 تقريبياً):</b>
- سيولة تقديرية لسوق العملات البديلة: <b>${alt_cap_billions:,.1f}B</b>
- القيمة التقديرية لإجمالى السوق: <b>${total_cap_trillions:,.2f}T</b>
- التغير الكلى لإجمالى القيمة السوقية آخر 24 ساعة: <b>{total_change:+.2f}%</b> → {total_trend}

📊 <b>هيمنة السوق:</b>
- هيمنة البيتكوين: <b>{btc_dom:.2f}%</b>
- هيمنة الإيثريوم: <b>{eth_dom:.2f}%</b>

💎 <b>تقييم الوضع العام:</b>
- {market_trend}

⚙️ <b>مستوى المخاطر (نظام التحذير الذكى):</b>
- {risk_emoji} <b>المخاطر حالياً عند مستوى:</b> {'منخفض' if risk_level=='low' else ('متوسط' if risk_level=='medium' else 'عالٍ')}
- {risk_message}

🧭 <b>التوقعات القادمة (وفق البيانات الحالية فقط):</b>
- استمرار تماسك البيتكوين أعلى مناطق الدعم الرئيسية يعزز فرص الاستقرار وتحسن الشهية للمخاطرة.
- كسر مناطق دعم قوية مع زيادة هبوط إجمالى القيمة السوقية قد يفتح المجال لموجات تصحيح أعمق، خاصة فى العملات البديلة ذات السيولة الضعيفة.
- أى تحسن واضح فى السيولة الداخلة للسوق مع صعود متدرج فى البيتكوين يعطى إشارات أفضل للتداول المضاربى.

📌 <b>الملخص النهائى:</b>
- السوق حالياً يتابع حركة البيتكوين والسيولة الداخلة والخارجة من العملات البديلة.
- يُفضّل التركيز على المناطق الواضحة للدعم والمقاومة مع عدم المبالغة فى الرافعة المالية.

⚠️ <b>رسالة اليوم من IN CRYPTO Ai:</b>
- لا تحاول مطاردة كل حركة؛ ركّز على الفرص الواضحة فقط واعتبر إدارة المخاطر جزءاً من استراتيجيتك، لا عبءً إضافياً.
- الصبر وعدم مطاردة الحركة يكون <b>أفضل من الدخول المتأخر</b> فى كثير من الأحيان.

IN CRYPTO Ai 🤖
""".strip()

    return report


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
            "كما يمكنك طلب تقرير السوق اليومى:\n"
            "➤ <code>/market</code> تقرير شامل عن البيتكوين و Total3.\n"
            "➤ <code>/risk_test</code> لاختبار مستوى المخاطر السريع.\n\n"
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

    # /vai  (هنا VAI → KuCoin تلقائياً لو مش موجودة فى Binance)
    if lower_text == "/vai":
        reply = format_analysis("VAIUSDT")
        send_message(chat_id, reply)
        return jsonify(ok=True)

    # تقرير السوق /market
    if lower_text == "/market":
        snapshot = build_market_snapshot()
        if not snapshot:
            send_message(
                chat_id,
                "⚠️ تعذر جلب بيانات السوق الكاملة فى الوقت الحالى.\n"
                "حاول مرة أخرى بعد قليل."
            )
        else:
            report = format_market_report(snapshot)
            send_message(chat_id, report)
        return jsonify(ok=True)

    # اختبار المخاطر /risk_test
    if lower_text == "/risk_test":
        snapshot = build_market_snapshot()
        if not snapshot:
            send_message(
                chat_id,
                "⚠️ تعذر جلب بيانات السوق لاختبار المخاطر الآن.\n"
                "حاول مرة أخرى بعد قليل."
            )
        else:
            risk_level = snapshot["risk_level"]
            risk_emoji = snapshot["risk_emoji"]
            risk_message = snapshot["risk_message"]
            btc_change = snapshot["btc_change"]
            total_change = snapshot["total_change"]
            btc_dom = snapshot["btc_dom"]
            eth_dom = snapshot["eth_dom"]

            reply = f"""
🧪 <b>اختبار سريع لمستوى المخاطر فى السوق</b>

- مستوى المخاطر الحالى: {risk_emoji} <b>{'منخفض' if risk_level=='low' else ('متوسط' if risk_level=='medium' else 'عالٍ')}</b>
- تغير البيتكوين آخر 24 ساعة: <b>{btc_change:+.2f}%</b>
- تغير إجمالى القيمة السوقية: <b>{total_change:+.2f}%</b>
- هيمنة البيتكوين: <b>{btc_dom:.2f}%</b> – هيمنة الإيثريوم: <b>{eth_dom:.2f}%</b>

<b>تفسير الذكاء الاصطناعى:</b>
{risk_message}
""".strip()
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
