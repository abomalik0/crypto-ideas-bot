import os
import logging
import requests
import threading
import time
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

# صاحب البوت (هيستقبل التنبيهات التلقائية)
OWNER_CHAT_ID = 669209875

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
#     دوال فورمات للأرقام
# ==============================

def fmt_price(value: float) -> str:
    """
    تنسيق رقم كبير بشكل لطيف (مستخدم فى التقرير).
    """
    try:
        if value is None:
            return "غير متاح"
        if value >= 1_000_000_000:
            return f"{value/1_000_000_000:.2f}B"
        if value >= 1_000_000:
            return f"{value/1_000_000:.2f}M"
        if value >= 1000:
            return f"{value:,.0f}".replace(",", ".")
        return f"{value:.2f}"
    except Exception:
        return str(value)


# ==============================
#     صياغة رسالة التحليل
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

    # ملاحظة الذكاء الاصطناعى – مع تلميح خاص لو السيولة أقل (KuCoin مثلاً)
    if exchange == "kucoin":
        ai_note = (
            "🤖 <b>ملاحظة الذكاء الاصطناعى:</b>\n"
            "السعر يتم تتبّعه عبر منصة سيولتها أقل من العملات الرئيسية، "
            "لذلك الحركة قد تكون أكثر حدة.\n"
            "استخدم حجم صفقات أصغر وركز على إدارة المخاطر.\n"
        )
    else:
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

📉 <b>RSI (تقديرى):</b>
- مؤشر القوة النسبية عند حوالى: <b>{rsi:.1f}</b> → {rsi_trend}

{ai_note}
""".strip()

    return msg


# ==============================
#   نظام مراقبة السوق (BTC + Total3)
# ==============================

# حالة المراقبة العالمية
LAST_ALT_MCAP = None          # آخر قيمة لسيولة العملات البديلة
LAST_ALT_MCAP_TS = 0          # وقت آخر قراءة
LAST_MARKET_ALERT_TS = 0      # آخر وقت تم إرسال تنبيه فيه
MARKET_ALERT_COOLDOWN = 20 * 60   # 20 دقيقة بين التنبيهات
MARKET_CHECK_INTERVAL = 10 * 60   # فحص كل 10 دقائق (خطة مجانية)


def fetch_btc_snapshot():
    """جلب لقطة سريعة للبيتكوين من Binance."""
    return fetch_from_binance("BTCUSDT")


def fetch_total3_snapshot():
    """
    جلب سيولة العملات البديلة (تقريبية) من CoinGecko:
    Total3 ≈ إجمالى السوق - (BTC + ETH)
    """
    try:
        url = "https://api.coingecko.com/api/v3/global"
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            logger.info("CoinGecko error %s: %s", r.status_code, r.text)
            return None

        data = (r.json() or {}).get("data") or {}
        total_mcap_usd = float((data.get("total_market_cap") or {}).get("usd") or 0.0)
        dom = data.get("market_cap_percentage") or {}
        btc_dom = float(dom.get("btc") or 0.0)
        eth_dom = float(dom.get("eth") or 0.0)

        alt_dom = max(0.0, 100.0 - btc_dom - eth_dom)
        alt_mcap = total_mcap_usd * (alt_dom / 100.0)

        return {
            "total_mcap": total_mcap_usd,
            "alt_mcap": alt_mcap,
            "alt_dom": alt_dom,
            "btc_dom": btc_dom,
            "eth_dom": eth_dom,
        }
    except Exception as e:
        logger.exception("Error fetching from CoinGecko: %s", e)
        return None


def analyze_market_for_alert(btc_data, total3_cur, alt_prev):
    """
    يحدد هل فى تنبيه مهم دلوقتى ولا لأ (ويوضح السبب).
    حساسيتنا هنا Ultra لكن مع كول داون.
    """
    if not btc_data or not total3_cur:
        return False, None, None, None

    btc_price = btc_data["price"]
    btc_change = btc_data["change_pct"]
    alt_mcap = total3_cur["alt_mcap"]

    alt_change_pct = None
    if alt_prev and alt_prev > 0:
        alt_change_pct = (alt_mcap - alt_prev) / alt_prev * 100.0

    mood = "calm"
    reason = None

    # حالات الخطر / الحركة القوية
    # 1) هبوط بيتكوين قوى
    if btc_change <= -3:
        mood = "down"
        reason = "هبوط يومى ملحوظ فى البيتكوين (أكثر من 3٪)، ما يعكس ضغط بيعى قوى."

    # 2) خروج سيولة من العملات البديلة بسرعة
    if alt_change_pct is not None and alt_change_pct <= -2:
        mood = "down"
        add = "انخفاض واضح فى سيولة العملات البديلة (Total3) بأكثر من 2٪ تقريبًا."
        reason = add if not reason else reason + " " + add

    # 3) حركة عنيفة لأعلى (مخاطرة / فرصة)
    if btc_change >= 4 or (alt_change_pct is not None and alt_change_pct >= 3):
        if mood == "calm":
            mood = "up"
            reason = "حركة صعودية قوية (إما فى البيتكوين أو فى سيولة العملات البديلة)، ما يزيد فرص الربح وأيضًا درجة المخاطرة."
        else:
            # لو فيه هبوط + حركة سيولة غريبة
            reason = (reason or "") + " مع حركة قوية فى السيولة، ما يزيد من حدة التذبذب."

    # لو مفيش أى سبب واضح، ما فى تنبيه
    if not reason:
        return False, None, None, None

    return True, mood, reason, alt_change_pct


def build_quick_alert_message(btc_data, total3_cur, mood, reason, alt_change_pct):
    """رسالة تنبيه سريعة قبل التقرير المفصل."""
    btc_price = btc_data["price"]
    btc_change = btc_data["change_pct"]

    alt_mcap = total3_cur["alt_mcap"]
    alt_dom = total3_cur["alt_dom"]

    if alt_change_pct is None:
        alt_line = f"سيولة العملات البديلة (تقريبًا): {fmt_price(alt_mcap)}$ (لا توجد مقارنة زمنية كافية بعد)."
    else:
        alt_line = (
            f"سيولة العملات البديلة (تقريبًا): {fmt_price(alt_mcap)}$ "
            f"({alt_change_pct:+.2f}٪ منذ آخر متابعة، هيمنة تقريبية: {alt_dom:.1f}٪)."
        )

    if mood == "down":
        mood_emoji = "⚠️"
        mood_title = "تنبيه هبوط / ضغط بيعى"
    else:
        mood_emoji = "🚀"
        mood_title = "تنبيه حركة قوية / زخم عالى"

    msg = f"""
{mood_emoji} <b>{mood_title} من IN CRYPTO Ai</b>

• بيتكوين: ~{fmt_price(btc_price)}$ ({btc_change:+.2f}٪ خلال 24 ساعة).
• {alt_line}

📌 <b>ملخص سريع:</b>
{reason}

سيتم إرسال تقرير مفصل عن حالة السوق بعد لحظات...
""".strip()

    return msg


def build_full_market_report(btc_data, total3_cur, alt_change_pct):
    """تقرير احترافى مدموج (BTC + سيولة العملات البديلة)."""
    btc_price = btc_data["price"]
    btc_change = btc_data["change_pct"]

    alt_mcap = total3_cur["alt_mcap"]
    total_mcap = total3_cur["total_mcap"]
    alt_dom = total3_cur["alt_dom"]
    btc_dom = total3_cur["btc_dom"]
    eth_dom = total3_cur["eth_dom"]

    today = datetime.utcnow().strftime("%Y-%m-%d")

    # توصيف بيتكوين
    if btc_change <= -3:
        btc_summary = "السوق ما زال يميل إلى الهبوط على المدى القصير، مع ضغط بيعى واضح على البيتكوين."
    elif btc_change <= -1:
        btc_summary = "البيتكوين يتعرض لتصحيح هابط خفيف إلى متوسط، دون علامات قوة صعودية واضحة حتى الآن."
    elif btc_change < 1:
        btc_summary = "البيتكوين يتحرك فى نطاق عرضى نسبياً مع تذبذب محدود."
    elif btc_change < 3:
        btc_summary = "البيتكوين يُظهر ميلاً صعودياً هادئاً مع تحسن تدريجى فى الزخم."
    else:
        btc_summary = "البيتكوين يتحرك فى موجة صعود قوية نسبياً، مع زيادة ملحوظة فى الزخم."

    # توصيف سيولة العملات البديلة
    if alt_change_pct is None:
        alt_summary = "لا توجد بيانات كافية بعد لقياس التغير اللحظى فى سيولة العملات البديلة."
    elif alt_change_pct <= -2:
        alt_summary = "هناك خروج ملحوظ للسيولة من العملات البديلة (Total3)، ما يزيد حساسية السوق لأى هبوط إضافى."
    elif alt_change_pct <= -0.5:
        alt_summary = "سيولة العملات البديلة تشهد تراجعاً خفيفاً، مع حذر واضح من المتداولين."
    elif alt_change_pct < 0.5:
        alt_summary = "سيولة العملات البديلة مستقرة تقريباً دون تغيرات كبيرة."
    elif alt_change_pct < 2:
        alt_summary = "هناك تدفق إيجابى معتدل للسيولة نحو العملات البديلة، ما قد يدعم فرص صعود انتقائية."
    else:
        alt_summary = "تدفّق قوى للسيولة نحو العملات البديلة، ما يعكس شهية مخاطرة مرتفعة وقد يصاحبه تذبذب عنيف."

    # تقييم عام
    if btc_change <= -2.5 or (alt_change_pct is not None and alt_change_pct <= -2):
        risk_eval = (
            "المخاطر حالياً مرتفعة نسبيًا، خاصةً مع تزايد احتمالات استمرار الهبوط أو توسع التصحيح.\n"
            "يُنصح بالتركيز على حماية رأس المال وتقليل حجم المراكز ذات الرافعة العالية."
        )
    elif btc_change >= 3 or (alt_change_pct is not None and alt_change_pct >= 2):
        risk_eval = (
            "السوق فى وضع زخم قوى (إما صعودى فى البيتكوين أو فى العملات البديلة)، "
            "ما يخلق فرصًا قوية لكن مع درجة مخاطرة أعلى من المعتاد."
        )
    else:
        risk_eval = (
            "المخاطر حاليًا متوسطة، مع توازن نسبى بين المشترين والبائعين، "
            "والأفضل انتظار تأكيد أوضح قبل زيادة حجم التعرض للسوق."
        )

    # توقعات عامة بسيطة
    expectations = (
        "• استمرار التماسك أعلى مناطق دعم رئيسية فى البيتكوين يعزّز فرص الاستقرار أو محاولات الصعود.\n"
        "• أى كسر واضح لمناطق دعم مهمة مع خروج سيولة من العملات البديلة قد يفتح الباب لتصحيح أعمق.\n"
        "• عودة السيولة بقوة إلى العملات البديلة مع استقرار البيتكوين عادةً ما تكون إشارة مبكرة لموجات مضاربية أقوى."
    )

    if alt_change_pct is None:
        alt_change_line = "لا توجد مقارنة زمنية كافية بعد لقياس تغير سيولة العملات البديلة منذ آخر متابعة."
    else:
        alt_change_line = f"تغير سيولة العملات البديلة منذ آخر متابعة: {alt_change_pct:+.2f}٪ تقريباً."

    text = f"""
تصحيح تاريخ التحليل ✅

🧭 <b>تحليل الذكاء الاصطناعي لسوق الكريبتو</b> – {today}

🏦 <b>نظرة عامة على البيتكوين:</b>
السعر الحالى للبيتكوين يدور حول ~<b>{fmt_price(btc_price)}$</b>.
نسبة التغير خلال 24 ساعة حوالى <b>{btc_change:+.2f}٪</b>.
{btc_summary}

🌐 <b>سيولة العملات البديلة (Total3 تقريبًا):</b>
- إجمالى قيمة السوق الكلية تقريبًا: <b>{fmt_price(total_mcap)}$</b>.
- سيولة تقديرية للعملات البديلة: <b>{fmt_price(alt_mcap)}$</b>.
- هيمنة البيتكوين: <b>{btc_dom:.1f}٪</b> – هيمنة الإيثيريوم: <b>{eth_dom:.1f}٪</b> – هيمنة العملات البديلة: <b>{alt_dom:.1f}٪</b>.
- {alt_change_line}
{alt_summary}

💎 <b>تقييم الوضع العام:</b>
{risk_eval}

⚙️ <b>التوقعات القادمة (وفق البيانات الحالية فقط):</b>
{expectations}

📌 <b>الملخص النهائي:</b>
> السوق يتحرك حاليًا بين تأثير حركة البيتكوين من جهة، وتدفق/خروج السيولة من العملات البديلة من جهة أخرى.
أفضل ما يمكن التركيز عليه الآن هو وضوح مناطق الدعم والمقاومة، مع الالتزام الصارم بإدارة رأس المال.

⚠️ <b>رسالة اليوم من IN CRYPTO Ai:</b>
> السوق دائمًا يحتوى على فرص، لكن البقاء فى السوق لفترة أطول يتطلب صبرًا وانضباطًا فى اتخاذ القرار.
لا تحاول مطاردة كل حركة؛ ركّز على الفرص الواضحة فقط، واعتبر إدارة المخاطر جزءًا من استراتيجية الربح، لا عائقًا له.  
IN CRYPTO Ai 🤖
""".strip()

    return text


def market_monitor_loop():
    """
    حلقة مراقبة السوق فى الخلفية:
    - تراقب BTCUSDT + سيولة العملات البديلة (Total3 تقريبًا).
    - حساسية عالية (Ultra) مع كول داون 20 دقيقة عشان ما يبقاش سبام.
    """
    global LAST_ALT_MCAP, LAST_ALT_MCAP_TS, LAST_MARKET_ALERT_TS

    logger.info("Market monitor thread started.")

    while True:
        try:
            logger.info("Market monitor: checking BTC + Total3...")
            btc_data = fetch_btc_snapshot()
            total3_cur = fetch_total3_snapshot()

            if not btc_data or not total3_cur:
                logger.info("Market monitor: missing data (btc or total3), skipping this round.")
            else:
                should_alert, mood, reason, alt_change_pct = analyze_market_for_alert(
                    btc_data, total3_cur, LAST_ALT_MCAP
                )
                now_ts = time.time()

                # تحديث آخر قيمة لسيولة العملات البديلة
                LAST_ALT_MCAP = total3_cur["alt_mcap"]
                LAST_ALT_MCAP_TS = now_ts

                if should_alert:
                    if (now_ts - LAST_MARKET_ALERT_TS) >= MARKET_ALERT_COOLDOWN:
                        # تنبيه سريع
                        quick_msg = build_quick_alert_message(
                            btc_data, total3_cur, mood, reason, alt_change_pct
                        )
                        send_message(OWNER_CHAT_ID, quick_msg)

                        # انتظر دقيقة ثم ابعت تقرير مفصل
                        time.sleep(60)
                        full_report = build_full_market_report(
                            btc_data, total3_cur, alt_change_pct
                        )
                        send_message(OWNER_CHAT_ID, full_report)

                        LAST_MARKET_ALERT_TS = now_ts
                    else:
                        logger.info("Market monitor: alert conditions met but still under cooldown.")
        except Exception as e:
            logger.exception("Market monitor error: %s", e)

        # انتظار حتى الفحص القادم
        time.sleep(MARKET_CHECK_INTERVAL)


def start_market_monitor_thread():
    t = threading.Thread(target=market_monitor_loop, daemon=True)
    t.start()


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
            "البوت يحاول أولاً جلب البيانات من Binance، "
            "وإذا لم يجد العملة يحاول تلقائياً من KuCoin.\n\n"
            "🔔 بالإضافة إلى ذلك: يوجد نظام تنبيهات ذكى يراقب حركة البيتكوين "
            "وسيولة العملات البديلة ويرسل لك تنبيه وتقرير تلقائياً عند حدوث تحركات قوية."
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

    # أمر اختبار يدوى لتقرير السوق الكامل (للاختبار فقط)
    if lower_text in ("/market", "/btcreport", "/btc_report"):
        try:
            btc_data = fetch_btc_snapshot()
            total3_cur = fetch_total3_snapshot()
            if not btc_data or not total3_cur:
                send_message(chat_id, "⚠️ تعذّر إنشاء تقرير السوق الآن، جرّب لاحقًا.")
            else:
                report = build_full_market_report(btc_data, total3_cur, None)
                send_message(chat_id, report)
        except Exception as e:
            logger.exception("Manual market report error: %s", e)
            send_message(chat_id, "⚠️ حدث خطأ أثناء إنشاء تقرير السوق.")
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
    start_market_monitor_thread()
    # تشغيل Flask على 8080
    app.run(host="0.0.0.0", port=8080)
