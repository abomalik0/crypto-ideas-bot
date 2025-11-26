import os
import logging
import threading
import time
from datetime import datetime

import requests
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

# صاحب البوت (يوصل له التنبيهات التلقائية)
OWNER_CHAT_ID = 669209875

# TradingView scan API (غير رسمى لكن شغال)
TRADINGVIEW_SCAN_URL = "https://scanner.tradingview.com/crypto/scan"

# Binance API
BINANCE_24H_TICKER = "https://api.binance.com/api/v3/ticker/24hr"

# إعداد اللوج
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Flask
app = Flask(__name__)

# ==============================
#   حالة السوق العامة (جلوَبل)
# ==============================

MARKET_STATE = {
    "btc_dominance": None,
    "eth_dominance": None,
    "total3_billion": None,
    "last_update_ts": 0,
    "btc_price": None,
    "btc_change_24h": None,
}

LAST_MARKET_ALERT_TS = 0
MARKET_ALERT_COOLDOWN = 60 * 30  # نصف ساعة بين كل تنبيه وتنبيه


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
        r = requests.get(BINANCE_24H_TICKER, params={"symbol": symbol}, timeout=10)
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
#     صياغة رسالة التحليل الفردى
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

    # نعرض الرمز بشكل موحّد لطيف
    base, binance_symbol, kucoin_symbol = normalize_symbol(user_symbol)
    display_symbol = binance_symbol

    # مستويات دعم / مقاومة بسيطة (تجريبية)
    support = round(low * 0.99, 6) if low > 0 else round(price * 0.95, 6)
    resistance = round(high * 1.01, 6) if high > 0 else round(price * 1.05, 6)

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
#   TradingView – BTC.D / ETH.D / TOTAL3
# ==============================

def fetch_tradingview_metrics():
    """
    يجلب:
    - BTC Dominance (CRYPTOCAP:BTC.D)
    - ETH Dominance (CRYPTOCAP:ETH.D)
    - TOTAL3 (سيولة العملات البديلة بمقياس B)
    من TradingView scan API.
    """
    try:
        payload = {
            "symbols": {
                "tickers": [
                    "CRYPTOCAP:BTC.D",
                    "CRYPTOCAP:ETH.D",
                    "CRYPTOCAP:TOTAL3",
                ],
                "query": {"types": []},
            },
            "columns": ["close"],
        }
        r = requests.post(TRADINGVIEW_SCAN_URL, json=payload, timeout=10)
        if r.status_code != 200:
            logger.warning("TradingView scan error: %s - %s", r.status_code, r.text)
            return None

        data = r.json()
        btc_d = None
        eth_d = None
        total3 = None

        for item in data.get("data", []):
            symbol = item.get("s")
            vals = item.get("d") or []
            if not vals:
                continue
            close_val = float(vals[0])

            if symbol == "CRYPTOCAP:BTC.D":
                btc_d = close_val
            elif symbol == "CRYPTOCAP:ETH.D":
                eth_d = close_val
            elif symbol == "CRYPTOCAP:TOTAL3":
                # TOTAL3 على TradingView غالباً بوحدة B (مليار)
                total3 = close_val

        if btc_d is None or eth_d is None or total3 is None:
            logger.warning("TradingView scan incomplete data: %s", data)
            return None

        return {
            "btc_dominance": btc_d,
            "eth_dominance": eth_d,
            "total3_billion": total3,
        }
    except Exception as e:
        logger.exception("Error fetching TradingView metrics: %s", e)
        return None


def fetch_btc_24h_from_binance():
    """
    يجلب سعر BTC والتغير اليومى من Binance فقط.
    """
    data = fetch_from_binance("BTCUSDT")
    if not data:
        return None, None
    return data["price"], data["change_pct"]


def evaluate_risk_level(btc_d, eth_d, total3_b, btc_change_24h):
    """
    تقييم بسيط للمخاطر (مود A حساس متوازن).
    يرجّع:
    - risk_level: low / medium / high
    - risk_emoji: 🟢 / 🟡 / 🔴
    - risk_message: نص مختصر
    """
    risk_score = 0
    reasons = []

    # هيمنة البيتكوين
    if btc_d >= 58:
        risk_score += 3
        reasons.append("هيمنة البيتكوين فوق 58٪ → ضغط على العملات البديلة.")
    elif btc_d >= 54:
        risk_score += 2
        reasons.append("هيمنة البيتكوين مرتفعة نسبيًا → سيولة أقل فى البدائل.")
    elif btc_d >= 50:
        risk_score += 1
        reasons.append("هيمنة البيتكوين حول 50٪ → توازن يميل لصالح البيتكوين.")

    # هيمنة الإيثريوم
    if eth_d >= 15:
        risk_score += 2
        reasons.append("هيمنة الإيثريوم مرتفعة → السوق يميل للكبار فقط.")
    elif eth_d <= 9:
        risk_score += 1
        reasons.append("هيمنة الإيثريوم ضعيفة نسبيًا → ضعف فى قطاع DeFi / L2.")

    # حجم سوق البدائل (TOTAL3)
    if total3_b < 500:
        risk_score += 3
        reasons.append("سيولة العملات البديلة ضعيفة (Total3 أقل من 500B تقريبًا).")
    elif total3_b < 700:
        risk_score += 2
        reasons.append("سيولة البدائل متوسطة وتميل للضعف.")
    elif total3_b < 900:
        risk_score += 1
        reasons.append("سيولة البدائل فى نطاق متوسط، تحتاج متابعة.")

    # تغير BTC اليومى
    if btc_change_24h is not None:
        if btc_change_24h <= -3:
            risk_score += 3
            reasons.append("هبوط يومى حاد فى البيتكوين (أكثر من -3٪).")
        elif btc_change_24h <= -1:
            risk_score += 2
            reasons.append("ميل سلبى فى حركة البيتكوين اليوم.")
        elif btc_change_24h >= 4:
            risk_score += 2
            reasons.append("صعود قوى فى البيتكوين → احتمال جنى أرباح عنيف.")
        elif btc_change_24h >= 1.5:
            risk_score += 1
            reasons.append("صعود إيجابى فى البيتكوين مع زخم ملحوظ.")

    # تحويل السكور لمستويات
    if risk_score >= 7:
        level = "high"
        emoji = "🔴"
        msg = "مستوى المخاطر حاليًا مرتفع، السوق حساس لأى هبوط أو خبر سلبى."
    elif risk_score >= 4:
        level = "medium"
        emoji = "🟡"
        msg = "مستوى المخاطر متوسط، السوق متذبذب ويحتاج حذر فى إدارة رأس المال."
    else:
        level = "low"
        emoji = "🟢"
        msg = "مستوى المخاطر منخفض نسبيًا، لكن يظل الالتزام بالخطة ضرورى."

    reasons_text = "\n".join(f"- {r}" for r in reasons) if reasons else "- لا توجد إشارات خطر حادة حاليًا."

    return level, emoji, msg, reasons_text


def build_market_snapshot():
    """
    يبنى صورة لحظية عن السوق:
    - BTC.D / ETH.D / TOTAL3 من TradingView
    - سعر BTC والتغير اليومى من Binance
    ويحدّث MARKET_STATE العالمي.
    """
    tv = fetch_tradingview_metrics()
    if not tv:
        return None

    btc_price, btc_change_24h = fetch_btc_24h_from_binance()

    MARKET_STATE["btc_dominance"] = tv["btc_dominance"]
    MARKET_STATE["eth_dominance"] = tv["eth_dominance"]
    MARKET_STATE["total3_billion"] = tv["total3_billion"]
    MARKET_STATE["btc_price"] = btc_price
    MARKET_STATE["btc_change_24h"] = btc_change_24h
    MARKET_STATE["last_update_ts"] = time.time()

    # altcap = total3 (لأن TOTAL3 فعلياً = إجمالى عملات بدون BTC و ETH)
    altcap_b = tv["total3_billion"]

    risk_level, risk_emoji, risk_msg, reasons_text = evaluate_risk_level(
        tv["btc_dominance"],
        tv["eth_dominance"],
        tv["total3_billion"],
        btc_change_24h,
    )

    snapshot = {
        "btc_price": btc_price,
        "btc_change_24h": btc_change_24h,
        "btc_dominance": tv["btc_dominance"],
        "eth_dominance": tv["eth_dominance"],
        "total3_billion": tv["total3_billion"],
        "altcap_billion": altcap_b,
        "risk_level": risk_level,
        "risk_emoji": risk_emoji,
        "risk_msg": risk_msg,
        "risk_reasons": reasons_text,
    }
    return snapshot


def format_market_report(snapshot):
    """
    يبنى تقرير /market احترافى بالعربى.
    """
    today = datetime.utcnow().strftime("%Y-%m-%d")

    btc_price = snapshot["btc_price"]
    btc_ch = snapshot["btc_change_24h"]
    btc_d = snapshot["btc_dominance"]
    eth_d = snapshot["eth_dominance"]
    total3 = snapshot["total3_billion"]
    altcap = snapshot["altcap_billion"]

    risk_level = snapshot["risk_level"]
    risk_emoji = snapshot["risk_emoji"]
    risk_msg = snapshot["risk_msg"]
    reasons_text = snapshot["risk_reasons"]

    # وصف عام بسيط حسب الهيمنة والسيولة
    if btc_d is not None and eth_d is not None:
        if btc_d >= 58:
            dom_text = "السوق حالياً تحت سيطرة البيتكوين بشكل واضح، ما يضغط على معظم العملات البديلة."
        elif btc_d >= 52:
            dom_text = "هيمنة البيتكوين مرتفعة لكن ليست قصوى، مع مساحة محدودة لحركة البدائل."
        else:
            dom_text = "هيمنة البيتكوين فى نطاق يسمح ببعض الفرص على العملات البديلة."

        if eth_d >= 13:
            eth_text = "الإيثريوم يحتفظ بحضور قوى، ما يدعم جزء من سوق DeFi و L2."
        else:
            eth_text = "هيمنة الإيثريوم ليست مرتفعة، ما يعكس حذر فى القطاعات المرتبطة به."
    else:
        dom_text = "لا يمكن حساب هيمنة البيتكوين والإيثريوم حالياً."
        eth_text = ""

    # نص التقرير
    lines = []

    lines.append(f"🧭 <b>تحليل الذكاء الاصطناعى لسوق الكريبتو</b> – {today}\n")

    if btc_price is not None and btc_ch is not None:
        lines.append(
            f"🏦 <b>البيتكوين:</b>\n"
            f"- السعر الحالى يدور حول: <b>{btc_price:.2f}$</b>\n"
            f"- تغير آخر 24 ساعة: <b>{btc_ch:.2f}%</b>\n"
        )

    if total3 is not None:
        lines.append(
            f"💰 <b>سيولة العملات البديلة (Total3):</b>\n"
            f"- حوالى: <b>{total3:.2f} مليار دولار</b>\n"
        )

    if btc_d is not None and eth_d is not None:
        lines.append(
            f"📊 <b>هيمنة السوق:</b>\n"
            f"- هيمنة البيتكوين: <b>{btc_d:.2f}%</b>\n"
            f"- هيمنة الإيثريوم: <b>{eth_d:.2f}%</b>\n"
        )

    lines.append("— — —")
    lines.append("📉 <b>قراءة هيكلة السوق:</b>")
    lines.append(f"- {dom_text}")
    if eth_text:
        lines.append(f"- {eth_text}")
    if altcap is not None:
        lines.append(
            f"- سيولة البدائل (خارج BTC و ETH) تقارب: <b>{altcap:.2f} مليار دولار</b>."
        )

    lines.append("— — —")
    lines.append("💎 <b>تقييم الوضع العام:</b>")
    if risk_level == "high":
        inv_text = (
            "استثماريًا: الأفضل حالياً هو التركيز على حماية رأس المال، "
            "وتجنب التوسع فى مراكز جديدة كبيرة."
        )
        trade_text = (
            "مضاربيًا: يُفضّل خفض الرافعة وتقليل التداول اليومى إلا فى الفرص الواضحة جداً."
        )
    elif risk_level == "medium":
        inv_text = (
            "استثماريًا: يمكن الاحتفاظ بالمراكز القوية مع تجنب الدخول العشوائى "
            "فى عملات منخفضة السيولة."
        )
        trade_text = (
            "مضاربيًا: السوق متذبذب، فيُفضّل الاعتماد على خطط دخول وخروج واضحة "
            "واستخدام وقف خسارة منضبط."
        )
    else:  # low
        inv_text = (
            "استثماريًا: البيئة الحالية مقبولة نسبيًا لبناء مراكز تدريجية، "
            "مع الأخذ فى الاعتبار أن المخاطر لا تختفى بالكامل."
        )
        trade_text = (
            "مضاربيًا: يمكن استغلال الحركات الفنية بشرط الالتزام بإدارة رأس مال صارمة."
        )

    lines.append(f"- {inv_text}")
    lines.append(f"- {trade_text}")

    lines.append("— — —")
    lines.append(f"{risk_emoji} <b>مستوى المخاطر اليومى:</b>")
    lines.append(f"{risk_msg}")
    lines.append("<b>تفاصيل الأسباب:</b>")
    lines.append(reasons_text)

    lines.append("— — —")
    lines.append("⚠️ <b>رسالة اليوم من IN CRYPTO Ai:</b>")
    if risk_level == "high":
        lines.append(
            "السوق حاليًا حساس وأى حركة عنيفة فى البيتكوين قد تؤدى إلى موجة هبوط "
            "سريعة فى العملات البديلة.\n"
            "الصبر وعدم المطاردة أفضل من الدخول المتأخر فى حركة قوية."
        )
    elif risk_level == "medium":
        lines.append(
            "السوق ليس فى وضع انهيار ولا فى وضع انطلاق كامل.\n"
            "الانضباط فى اختيار الفرص أهم من عدد الصفقات."
        )
    else:
        lines.append(
            "رغم أن مستوى المخاطر منخفض نسبيًا، تذكّر أن الكريبتو سوق عالى التذبذب.\n"
            "لا تدع الهدوء الظاهرى يخدعك عن أهمية خطة الخروج."
        )

    lines.append("\nIN CRYPTO Ai 🤖")

    return "\n".join(lines)


def maybe_send_market_alert(snapshot):
    """
    يقرر إذا كان لازم يرسل تنبيه سوقى تلقائى للـ OWNER_CHAT_ID.
    يعتمد على مستوى المخاطر وبعض العتبات.
    """
    global LAST_MARKET_ALERT_TS

    now_ts = time.time()
    if now_ts - LAST_MARKET_ALERT_TS < MARKET_ALERT_COOLDOWN:
        return

    risk_level = snapshot["risk_level"]
    btc_d = snapshot["btc_dominance"]
    total3 = snapshot["total3_billion"]

    should_alert = False
    alert_reason = []

    if risk_level == "high":
        should_alert = True
        alert_reason.append("مستوى المخاطر العام مرتفع.")
    if btc_d is not None and btc_d >= 58:
        should_alert = True
        alert_reason.append("هيمنة البيتكوين فوق 58٪.")
    if total3 is not None and total3 < 600:
        should_alert = True
        alert_reason.append("سيولة البدائل عند مستويات ضعيفة (Total3 < 600B).")

    if not should_alert:
        return

    reason_text = "\n".join(f"- {r}" for r in alert_reason) if alert_reason else "- بدون تفاصيل إضافية."

    msg = f"""
🔔 <b>تنبيه مهم من IN CRYPTO Ai</b>

تم رصد ظروف سوقية قد تحمل مخاطر أعلى من المعتاد:

{reason_text}

<b>مستوى المخاطر الحالى:</b> {snapshot['risk_emoji']} ({snapshot['risk_level']})

يُفضَّل مراجعة تقرير السوق الكامل عبر الأمر:
<code>/market</code>
""".strip()

    send_message(OWNER_CHAT_ID, msg)
    LAST_MARKET_ALERT_TS = now_ts


def market_monitor_loop():
    """
    حلقة مراقبة خلفية للسوق (BTC.D / ETH.D / TOTAL3 + BTC).
    تعمل طول ما السيرفر شغال، وتبعت تنبيه لو فى خطر.
    """
    logger.info("Market monitor loop started.")
    while True:
        try:
            snap = build_market_snapshot()
            if snap:
                maybe_send_market_alert(snap)
        except Exception as e:
            logger.exception("Error in market_monitor_loop: %s", e)
        # فترة الانتظار بين كل فحص والتانى (مثلاً 3 دقائق)
        time.sleep(180)


# ==============================
#          مسارات Flask
# ==============================

@app.route("/", methods=["GET"])
def index():
    return "IN CRYPTO Ai bot is running.", 200


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
            "أوامر التحليل الفردى للعملات:\n"
            "➤ <code>/btc</code>\n"
            "➤ <code>/vai</code>\n"
            "➤ <code>/coin btc</code>\n"
            "➤ <code>/coin btcusdt</code>\n"
            "➤ <code>/coin hook</code> أو أى رمز آخر.\n\n"
            "أوامر السوق العامة:\n"
            "➤ <code>/market</code>  → تقرير شامل عن هيمنة السوق وسيولة البدائل.\n"
            "➤ <code>/risk_test</code> → اختبار سريع لمستوى المخاطر الحالى.\n\n"
            "البوت يحاول أولاً جلب البيانات من Binance، "
            "ولو الرمز مش موجود يحاول تلقائيًا من KuCoin، "
            "ويستخدم TradingView لمؤشرات هيمنة السوق (BTC.D / ETH.D / TOTAL3)."
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

    # /market → تقرير السوق الاحترافى
    if lower_text == "/market":
        snap = build_market_snapshot()
        if not snap:
            send_message(
                chat_id,
                "⚠️ تعذَّر جلب بيانات السوق العامة حاليًا، حاول مرة أخرى بعد قليل.",
            )
        else:
            report = format_market_report(snap)
            send_message(chat_id, report)
        return jsonify(ok=True)

    # /risk_test → اختبار سريع لمستوى المخاطر
    if lower_text == "/risk_test":
        snap = build_market_snapshot()
        if not snap:
            send_message(
                chat_id,
                "⚠️ تعذَّر جلب بيانات المخاطر حاليًا، حاول مرة أخرى بعد قليل.",
            )
        else:
            msg_txt = (
                f"{snap['risk_emoji']} <b>مستوى المخاطر الحالى:</b> {snap['risk_level']}\n\n"
                f"{snap['risk_msg']}\n\n"
                f"<b>ملخص الأسباب:</b>\n"
                f"{snap['risk_reasons']}\n\n"
                "لرؤية تقرير السوق الكامل استخدم الأمر:\n"
                "<code>/market</code>"
            )
            send_message(chat_id, msg_txt)
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


def start_market_monitor_thread():
    t = threading.Thread(target=market_monitor_loop, daemon=True)
    t.start()
    logger.info("Market monitor thread started.")


if __name__ == "__main__":
    logger.info("Bot is starting...")
    setup_webhook()
    start_market_monitor_thread()
    # تشغيل Flask على 8080
    app.run(host="0.0.0.0", port=8080)
