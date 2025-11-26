import os
import logging
import requests
from datetime import datetime, timezone
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
            "تأكد من الرمز (مثال: <code>BTC</code> أو <code>BTCUSDT</code> أو <code>VAI</code>) "
            "وحاول مرة أخرى."
        )

    price = data["price"]
    change = data["change_pct"]
    high = data["high"]
    low = data["low"]
    exchange = data["exchange"]

    base, binance_symbol, kucoin_symbol = normalize_symbol(user_symbol)
    display_symbol = (binance_symbol if exchange == "binance" else kucoin_symbol).replace("-", "")

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

    if exchange == "kucoin":
        source_note = (
            "⚙️ <b>ملاحظة المنصة:</b> يتم جلب بيانات هذه العملة من KuCoin بسبب عدم توافرها على Binance "
            "أو ضعف السيولة هناك، لذلك يكون التحليل مبسّط ومحافظ.\n\n"
        )
    else:
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
#       بيانات السوق من CoinGecko
# ==============================

COINGECKO_BASE = "https://api.coingecko.com/api/v3"


def fetch_coingecko_global():
    """جلب بيانات السوق العامة من CoinGecko."""
    try:
        url = f"{COINGECKO_BASE}/global"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            logger.warning("CoinGecko /global error: %s - %s", r.status_code, r.text)
            return None
        return r.json().get("data") or {}
    except Exception as e:
        logger.exception("Error fetching CoinGecko global: %s", e)
        return None


def fetch_coingecko_btc_eth():
    """جلب سعر وتغير البيتكوين والإيثريوم."""
    try:
        url = f"{COINGECKO_BASE}/simple/price"
        params = {
            "ids": "bitcoin,ethereum",
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        }
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            logger.warning("CoinGecko /simple/price error: %s - %s", r.status_code, r.text)
            return None
        return r.json()
    except Exception as e:
        logger.exception("Error fetching CoinGecko BTC/ETH: %s", e)
        return None


def build_market_snapshot():
    """
    يبنى Snapshot موحّد للسوق:
    - btc_price, btc_change_24h
    - total_mcap, total_volume_24h
    - btc_dom, eth_dom
    - alt_mcap, alt_share, alt_change_est
    """
    global_data = fetch_coingecko_global()
    price_data = fetch_coingecko_btc_eth()

    if not global_data or not price_data:
        return None

    market_cap = global_data.get("total_market_cap") or {}
    volume = global_data.get("total_volume") or {}
    mcap_pct = global_data.get("market_cap_percentage") or {}

    total_mcap = float(market_cap.get("usd") or 0.0)
    total_volume = float(volume.get("usd") or 0.0)

    btc_dom = float(mcap_pct.get("btc") or 0.0)
    eth_dom = float(mcap_pct.get("eth") or 0.0)

    btc_info = price_data.get("bitcoin") or {}
    eth_info = price_data.get("ethereum") or {}

    btc_price = float(btc_info.get("usd") or 0.0)
    btc_change_24h = float(btc_info.get("usd_24h_change") or 0.0)

    eth_price = float(eth_info.get("usd") or 0.0)
    eth_change_24h = float(eth_info.get("usd_24h_change") or 0.0)

    # تقدير القيمة السوقية للبيتكوين والإيثريوم من الهيمنة
    btc_mcap = total_mcap * (btc_dom / 100.0)
    eth_mcap = total_mcap * (eth_dom / 100.0)
    alt_mcap = max(total_mcap - btc_mcap - eth_mcap, 0.0)
    alt_share = 100.0 - btc_dom - eth_dom

    # تقدير تغير سيولة العملات البديلة بشكل تقريبى
    avg_major_change = (btc_change_24h + eth_change_24h) / 2.0
    total_change_24h = float(global_data.get("market_cap_change_percentage_24h_usd") or 0.0)
    alt_change_est = total_change_24h - avg_major_change * (btc_dom + eth_dom) / 100.0

    snapshot = {
        "btc_price": btc_price,
        "btc_change_24h": btc_change_24h,
        "eth_price": eth_price,
        "eth_change_24h": eth_change_24h,
        "total_mcap": total_mcap,
        "total_volume": total_volume,
        "btc_dom": btc_dom,
        "eth_dom": eth_dom,
        "alt_mcap": alt_mcap,
        "alt_share": alt_share,
        "total_change_24h": total_change_24h,
        "alt_change_est": alt_change_est,
    }
    return snapshot
    # ==============================
#        نظام تقييم المخاطر
# ==============================

def evaluate_risk_level(snapshot):
    """
    تقييم مبسط للمخاطر على السوق ككل.
    يرجّع:
    - risk_level: 'low' | 'medium' | 'high'
    - risk_emoji
    - risk_message (عربى مختصر)
    """
    btc_ch = snapshot["btc_change_24h"]
    total_ch = snapshot["total_change_24h"]
    btc_dom = snapshot["btc_dom"]
    alt_ch = snapshot["alt_change_est"]

    risk_score = 0.0

    if abs(btc_ch) > 3:
        risk_score += 1.0
    if btc_ch < -3:
        risk_score += 1.0

    if total_ch < -2:
        risk_score += 1.0
    elif total_ch > 2:
        risk_score -= 0.3

    if alt_ch < -3:
        risk_score += 0.7
    elif alt_ch > 2:
        risk_score -= 0.3

    if btc_dom > 58:
        risk_score += 0.7
    elif btc_dom < 50:
        risk_score -= 0.3

    if risk_score <= 0.5:
        level = "low"
        emoji = "🟢"
        message = (
            "المخاطر حاليًا منخفضة نسبيًا مع توازن بين المشترين والبائعين، "
            "لكن يفضّل دائمًا الالتزام بخطة إدارة رأس المال."
        )
    elif risk_score <= 1.5:
        level = "medium"
        emoji = "🟡"
        message = (
            "المخاطر حالياً متوسطة؛ السوق يشهد تذبذبًا واضحًا، "
            "ويفضّل التركيز على الفرص الواضحة وتخفيف الرافعة المالية."
        )
    else:
        level = "high"
        emoji = "🔴"
        message = (
            "المخاطر حالياً مرتفعة؛ حركة السوق عنيفة أو غير مستقرة، "
            "ويفضّل تقليل حجم الصفقات أو الانتظار حتى هدوء الحركة."
        )

    return level, emoji, message


# ==============================
#        تقرير السوق /market
# ==============================

def format_market_report():
    snapshot = build_market_snapshot()
    if not snapshot:
        return (
            "⚠️ لا يمكن جلب بيانات السوق الآن من CoinGecko.\n"
            "حاول مرة أخرى بعد قليل."
        )

    risk_level, risk_emoji, risk_message = evaluate_risk_level(snapshot)

    now_utc = datetime.now(timezone.utc)
    date_str = now_utc.strftime("%Y-%m-%d")
    day_str = now_utc.strftime("%d")

    btc_price = snapshot["btc_price"]
    btc_change = snapshot["btc_change_24h"]
    eth_price = snapshot["eth_price"]
    eth_change = snapshot["eth_change_24h"]
    total_mcap = snapshot["total_mcap"]
    total_volume = snapshot["total_volume"]
    btc_dom = snapshot["btc_dom"]
    eth_dom = snapshot["eth_dom"]
    alt_mcap = snapshot["alt_mcap"]
    alt_share = snapshot["alt_share"]
    total_change = snapshot["total_change_24h"]
    alt_change = snapshot["alt_change_est"]

    if btc_change > 1.5:
        btc_trend = "صعودى واضح مع تحسن فى شهية المخاطرة."
    elif btc_change > 0:
        btc_trend = "ميل صاعد هادئ مع تماسك فوق مناطق دعم مهمة."
    elif btc_change > -2:
        btc_trend = "تذبذب مائل للهبوط الخفيف يحتاج مراقبة."
    else:
        btc_trend = "ضغط بيعى واضح على البيتكوين فى المدى القصير."

    if alt_change > 2:
        alt_trend = "سيولة إيجابية نسبيًا للعملات البديلة مع تحسن فى بعض القطاعات."
    elif alt_change > -1:
        alt_trend = "سيولة متوازنة للعملات البديلة بدون حركة عنيفة."
    elif alt_change > -3:
        alt_trend = "ضعف بسيط فى سيولة العملات البديلة؛ يفضّل اختيار المشاريع بعناية."
    else:
        alt_trend = "ضغط قوى على سيولة العملات البديلة (حالة نزيف محتملة)."

    if total_change > 2:
        market_trend = "السوق يميل إلى الصعود مع دخول سيولة جديدة نسبيًا."
    elif total_change > -1:
        market_trend = "السوق حالياً متوازن مع تذبذب طبيعى داخل نطاق سعرى."
    elif total_change > -3:
        market_trend = "السوق يميل للهبوط الخفيف؛ يحتاج لمراقبة حجم السيولة."
    else:
        market_trend = "السوق يشهد ضغوط بيعية ملحوظة؛ يُفضّل الحذر فى الدخول الجديد."

    if risk_level == "low":
        risk_label = "منخفض"
    elif risk_level == "medium":
        risk_label = "متوسط"
    else:
        risk_label = "مرتفع"

    btc_price_str = f"{btc_price:,.0f}"
    eth_price_str = f"{eth_price:,.0f}"
    total_cap_str = f"{total_mcap/1e9:,.2f}B"
    alt_cap_str = f"{alt_mcap/1e9:,.2f}B"
    volume_str = f"{total_volume/1e9:,.2f}B"

    report = (
        f"✅ <b>تحليل الذكاء الاصطناعى لسوق الكريبتو</b>\n"
        f"📅 <b>التاريخ:</b> {date_str} (اليوم {day_str})\n\n"
        f"🏛 <b>نظرة عامة على البيتكوين:</b>\n"
        f"- السعر الحالى للبيتكوين: <b>${btc_price_str}</b>\n"
        f"- نسبة تغير خلال 24 ساعة: <b>{btc_change:+.2f}%</b>\n"
        f"- {btc_trend}\n\n"
        f"🌍 <b>نظرة عامة على سيولة السوق:</b>\n"
        f"- القيمة التقديرية للسوق الكلى: <b>{total_cap_str}</b>\n"
        f"- تقدير سيولة العملات البديلة (AltCap تقريبًا): <b>{alt_cap_str}</b>\n"
        f"- حجم تداول تقريبى خلال 24 ساعة: <b>{volume_str}</b>\n"
        f"- تقدير تغير سيولة العملات البديلة: <b>{alt_change:+.2f}%</b>\n"
        f"- {alt_trend}\n\n"
        f"📊 <b>هيمنة السوق:</b>\n"
        f"- هيمنة البيتكوين: <b>{btc_dom:.2f}%</b>\n"
        f"- هيمنة الإيثريوم: <b>{eth_dom:.2f}%</b>\n"
        f"- حصة تقريبية لباقى العملات (Alt Share): <b>{alt_share:.2f}%</b>\n"
        f"- التغير الكلى لإجمالى القيمة السوقية 24 ساعة: <b>{total_change:+.2f}%</b>\n\n"
        f"💎 <b>تقييم الوضع العام:</b>\n"
        f"- {market_trend}\n"
        f"- مستوى المخاطر الحالى (نظام التحذير الذكى): {risk_emoji} <b>{risk_label}</b>\n"
        f"- {risk_message}\n\n"
        f"⚙️ <b>التوقعات القادمة (وفق البيانات الحالية فقط):</b>\n"
        f"- استمرار تماسك البيتكوين أعلى مناطق الدعم المهمة يدعم فرص الاستقرار وتحسن تدريجى.\n"
        f"- أى هبوط حاد مع زيادة فى هيمنة البيتكوين قد يضغط على العملات البديلة بقوة.\n"
        f"- تحسن ملحوظ فى سيولة العملات البديلة مع ثبات هيمنة البيتكوين قد يعطى فرص مضاربية أفضل.\n\n"
        f"📌 <b>الملخص النهائى:</b>\n"
        f"- السوق حاليًا يتابع حركة البيتكوين والسيولة الداخلة والخارجة من العملات البديلة.\n"
        f"- يفضّل التركيز على المناطق الواضحة للدعم والمقاومة مع عدم المبالغة فى الرافعة المالية.\n\n"
        f"⚠️ <b>رسالة اليوم من IN CRYPTO Ai:</b>\n"
        f"- لا تحاول مطاردة كل حركة؛ ركّز على الفرص الواضحة فقط واعتبر إدارة المخاطر جزءًا أساسيًا من استراتيجيتك.\n"
        f"- الصبر فى أوقات التذبذب يكون غالبًا أفضل من الدخول المتأخر فى حركة قوية.\n\n"
        f"IN CRYPTO Ai 🤖"
    )

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

    if lower_text == "/start":
        welcome = (
            "👋 أهلاً بك فى بوت <b>IN CRYPTO Ai</b>.\n\n"
            "يمكنك طلب تحليل فنى لأى عملة:\n"
            "➤ <code>/btc</code>\n"
            "➤ <code>/vai</code>\n"
            "➤ <code>/coin btc</code>\n"
            "➤ <code>/coin btcusdt</code>\n"
            "➤ <code>/coin hook</code> أو أى رمز آخر.\n\n"
            "ويمكنك طلب تقرير السوق العام:\n"
            "➤ <code>/market</code>\n"
            "➤ <code>/risk_test</code> لعرض مستوى المخاطر الحالى فقط.\n\n"
            "البوت يحاول أولاً جلب البيانات من Binance، "
            "وإذا لم يجد العملة يحاول تلقائياً من KuCoin."
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

    if lower_text == "/market":
        reply = format_market_report()
        send_message(chat_id, reply)
        return jsonify(ok=True)

    if lower_text == "/risk_test":
        snapshot = build_market_snapshot()
        if not snapshot:
            send_message(
                chat_id,
                "⚠️ لا يمكن جلب بيانات السوق الآن من CoinGecko.\n"
                "حاول مرة أخرى بعد قليل.",
            )
            return jsonify(ok=True)

        risk_level, risk_emoji, risk_message = evaluate_risk_level(snapshot)
        if risk_level == "low":
            risk_label = "منخفض"
        elif risk_level == "medium":
            risk_label = "متوسط"
        else:
            risk_label = "مرتفع"

        msg_text = (
            f"⚙️ <b>اختبار المخاطر السريع (Risk Test)</b>\n\n"
            f"- مستوى المخاطر الحالى: {risk_emoji} <b>{risk_label}</b>\n"
            f"- {risk_message}\n\n"
            f"يمكنك طلب تقرير كامل باستخدام الأمر <code>/market</code>."
        )
        send_message(chat_id, msg_text)
        return jsonify(ok=True)

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
    app.run(host="0.0.0.0", port=8080)
