import time
import math
from datetime import datetime

import requests

import config

# =========================================================
#                 إعدادات و ثوابت عامة
# =========================================================

BINANCE_API = "https://api.binance.com"
KUCOIN_API = "https://api.kucoin.com"

# لو حابب تغيرها، خليها من config
MARKET_TTL_SECONDS = getattr(config, "MARKET_TTL_SECONDS", 30)


# =========================================================
#            دوال مساعدة لجلب بيانات السوق
# =========================================================

def _fetch_binance_24h(symbol: str) -> dict | None:
    """
    يرجع بيانات 24 ساعة من بينانس:
    السعر الحالى، أعلى/أدنى، التغير فى 24 ساعة، الحجم...
    """
    try:
        r = config.HTTP_SESSION.get(
            f"{BINANCE_API}/api/v3/ticker/24hr",
            params={"symbol": symbol},
            timeout=10,
        )
        if r.status_code != 200:
            config.logger.warning("Binance 24h error %s: %s", r.status_code, r.text)
            return None
        return r.json()
    except Exception as e:
        config.logger.exception("Binance 24h exception: %s", e)
        return None


def _safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _estimate_rsi(change_pct: float, range_pct: float) -> float:
    """
    تقدير تقريبى لـ RSI بناءً على التغير و مدى الحركة.
    مش RSI حقيقى لكن بيعطى إحساس عام.
    """
    # نطاق من 30 إلى 70 تقريباً
    base = 50 + change_pct * 1.2
    base += (range_pct - 5) * 0.4
    return max(10.0, min(90.0, base))


def _strength_label(change_pct: float, range_pct: float) -> str:
    if change_pct <= -7:
        return "هبوط حاد / Panic"
    if change_pct <= -4:
        return "ضغط بيعى قوى"
    if change_pct <= -2:
        return "ميل هابط واضح"
    if change_pct < 2:
        return "حركة جانبية / تذبذب"
    if change_pct < 5:
        return "ميل صاعد هادئ"
    return "صعود قوى / زخم عالى"


def _liquidity_pulse(change_pct: float, volume_usd: float) -> str:
    if volume_usd <= 0:
        return "السيولة غير واضحة"
    if volume_usd < 1e9:
        base = "سيولة متوسطة"
    elif volume_usd < 3e9:
        base = "سيولة مرتفعة نسبياً"
    else:
        base = "سيولة قوية جداً"

    if change_pct <= -4:
        return f"{base} مع خروج سيولة بيعية ملحوظ"
    if change_pct >= 4:
        return f"{base} مع دخول سيولة شرائية ملحوظة"
    return f"{base} مع توازن نسبى بين المشترين والبائعين"


# =========================================================
#            جلب و كاش بيانات السوق (BTCUSDT)
# =========================================================

def get_market_metrics(symbol: str = "BTCUSDT") -> dict | None:
    """
    يرجع dict فيها مقاييس السوق الأساسية لـ BTC:
    السعر الحالى، التغير، المدى، التقلب، ... إلخ.
    يستخدم كاش داخلى فى config.MARKET_METRICS_CACHE.
    """
    cache = config.MARKET_METRICS_CACHE.get(symbol)
    now = time.time()

    if cache and (now - cache.get("ts", 0)) < MARKET_TTL_SECONDS:
        return cache

    data = _fetch_binance_24h(symbol)
    if not data:
        return cache  # على الأقل نرجع آخر قيمة متاحة

    last_price = _safe_float(data.get("lastPrice"))
    open_price = _safe_float(data.get("openPrice"))
    high_price = _safe_float(data.get("highPrice"))
    low_price = _safe_float(data.get("lowPrice"))
    volume = _safe_float(data.get("volume"))
    quote_volume = _safe_float(data.get("quoteVolume"))

    if last_price <= 0 or open_price <= 0:
        config.logger.warning("Invalid price data from Binance: %s", data)
        return cache

    # نسبة التغير فى 24 ساعة
    change_pct = ((last_price - open_price) / open_price) * 100.0

    # مدى الحركة كنسبة من السعر الحالى
    range_pct = 0.0
    if high_price > 0 and low_price > 0:
        range_pct = ((high_price - low_price) / last_price) * 100.0

    # تقدير "درجة التقلب" من 0 إلى 100 تقريباً
    volatility_score = max(0.0, min(100.0, range_pct * 1.8))

    # تريليونات / مليارات / ملايين دولار حجم
    volume_usd = quote_volume
    rsi_est = _estimate_rsi(change_pct, range_pct)

    strength = _strength_label(change_pct, range_pct)
    liq_pulse = _liquidity_pulse(change_pct, volume_usd)

    distance_from_low = 0.0
    if last_price > 0 and low_price > 0:
        distance_from_low = (last_price - low_price) / last_price * 100.0

    metrics = {
        "symbol": symbol,
        "price": last_price,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "volume": volume,
        "quote_volume": quote_volume,
        "change_pct": change_pct,
        "range_pct": range_pct,
        "volatility_score": volatility_score,
        "volume_usd": volume_usd,
        "rsi_est": rsi_est,
        "strength_label": strength,
        "liquidity_pulse": liq_pulse,
        "distance_from_low_pct": distance_from_low,
        "ts": now,
        "ts_iso": datetime.utcnow().isoformat(timespec="seconds"),
    }

    config.MARKET_METRICS_CACHE[symbol] = metrics
    return metrics


def get_market_metrics_cached() -> dict | None:
    """اختصار لاستدعاء مقاييس BTC من الكاش."""
    return get_market_metrics("BTCUSDT")


# =========================================================
#           تقييم المخاطر و تحويلها لنص عربى
# =========================================================

def evaluate_risk_level(change_pct: float, volatility_score: float) -> dict:
    """
    يرجع dict:
    {
        "level": "low" / "medium" / "high",
        "emoji": "🟢",
        "message": "..."
    }
    """
    level = "low"
    emoji = "🟢"
    message = "المخاطر العامة حالياً منخفضة نسبياً مع إمكانية تذبذب طبيعى."

    # مخاطر عالية جداً
    if change_pct <= -7 or (change_pct <= -5 and volatility_score >= 40):
        level = "high"
        emoji = "🟥"
        message = (
            "يوجد ضغط بيعى حاد واحتمال موجة Panic أو تصفية مراكز كبيرة. "
            "يفضّل تقليل الرافعة وضبط أوامر الوقف بدقة، وتجنب المضاربات العشوائية."
        )
    # مخاطر متوسطة
    elif change_pct <= -3 or volatility_score >= 25:
        level = "medium"
        emoji = "🟠"
        message = (
            "السوق فى حالة حساسة مع تذبذب أعلى من المعتاد. "
            "المتداول قصير المدى يحتاج لوقف خسارة واضح وحجم صفقة صغير."
        )

    return {
        "level": level,
        "emoji": emoji,
        "message": message,
    }


def _risk_level_ar(level: str) -> str:
    if level == "high":
        return "عالى جداً"
    if level == "medium":
        return "متوسط"
    return "منخفض"


# =========================================================
#      تقدير أهداف الهبوط (مناطق دعم تقريبية)
# =========================================================

def _estimate_drop_targets(price: float, change_pct: float, volatility_score: float):
    """
    يرجع (target1, target2, comment)
    الهدفين عبارة عن مناطق دعم تقريبية لو استمر الضغط البيعى.
    """
    if price <= 0:
        return None, None, "البيانات غير كافية لتحديد أهداف هبوط دقيقة."

    # شدة الحركة الحالية
    severity = abs(change_pct) * 0.6 + volatility_score * 0.4
    severity = max(3.0, min(22.0, severity))

    # الهدف الأول: Drop خفيف/متوسط
    drop1 = min(12.0, max(2.5, severity * 0.55))
    # الهدف الثانى: Drop أعمق لو استمر الذعر
    drop2 = min(25.0, drop1 + severity * 0.5)

    t1 = price * (1 - drop1 / 100.0)
    t2 = price * (1 - drop2 / 100.0)

    comment = (
        "هذه الأهداف تقديرية وليست مناطق دعم كلاسيكية ثابتة؛ "
        "هى مجرد نطاقات محتملة لو استمر الضغط البيعى بنفس الوتيرة."
    )
    return t1, t2, comment


# =========================================================
#       منطق اكتشاف حالة تستحق تحذير (Smart Alert)
# =========================================================

def detect_alert_condition(metrics: dict, risk: dict) -> str | None:
    """
    لو مفيش تحذير → يرجع None.
    لو فى تحذير → يرجع reason_key نصية تستخدم لتجنب التكرار.
    """
    if not metrics or not risk:
        return None

    change_pct = metrics["change_pct"]
    vol = metrics["volatility_score"]
    dist_low = metrics.get("distance_from_low_pct", 0.0)
    range_pct = metrics.get("range_pct", 0.0)

    level = risk["level"]

    # شرط 1: هبوط حاد وفجائى وقريب من قاع اليوم
    if change_pct <= -5 and dist_low < 1.2 and range_pct >= 5:
        bucket = int(abs(change_pct))  # تقريب بالسالب
        return f"panic_near_low_{bucket}"

    # شرط 2: هبوط كبير > -7% أياً كان موقع السعر
    if change_pct <= -7:
        bucket = int(abs(change_pct))
        return f"massive_drop_{bucket}"

    # شرط 3: ضغط بيعى قوى + تقلب عالى + ريسك High
    if level == "high" and vol >= 35 and change_pct <= -4:
        zone = int(abs(change_pct))
        return f"high_risk_zone_{zone}"

    # شرط 4: تحذير مبكر: انتقال من low → medium risk مع تذبذب كبير
    if level == "medium" and change_pct <= -3 and range_pct >= 6:
        zone = int(abs(change_pct))
        return f"early_warning_{zone}"

    return None


# =========================================================
#        تنسيقات الرسائل (Analysis / Market / Risk)
# =========================================================

def format_analysis(symbol: str = "BTCUSDT") -> str:
    metrics = get_market_metrics(symbol)
    if not metrics:
        return "⚠️ تعذّر جلب بيانات السوق حالياً، حاول بعد قليل."

    price = metrics["price"]
    change_pct = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    rsi = metrics["rsi_est"]
    vol_score = metrics["volatility_score"]
    strength = metrics["strength_label"]
    liq = metrics["liquidity_pulse"]
    high = metrics["high"]
    low = metrics["low"]

    direction = "صاعد" if change_pct > 0 else "هابط" if change_pct < 0 else "جانبى"
    sign = "+" if change_pct >= 0 else ""

    text = f"""
📊 تحليل سريع للعملة: <b>{symbol}</b>

💰 السعر الحالى: <b>${price:,.0f}</b>
📈 تغير 24 ساعة: <b>{sign}{change_pct:.2f}%</b>
🔁 مدى الحركة (High/Low): <b>{range_pct:.2f}%</b>
📍 أعلى/أدنى يومى: <b>${high:,.0f}</b> / <b>${low:,.0f}</b>

🧭 قراءة عامة:
• الاتجاه العام الآن: <b>{direction}</b>
• قوة الحركة: <b>{strength}</b>
• درجة التقلب الحالية: <b>{vol_score:.1f} / 100</b>
• تقدير RSI الحالى: <b>{rsi:.1f}</b>
• نبض السيولة: <b>{liq}</b>

ℹ️ هذه القراءة تعتمد على بيانات لحظية من بينانس، ويتم تبسيط المؤشرات لتناسب عرض تيليجرام.
"""
    return text.strip()


def format_market_report() -> str:
    metrics = get_market_metrics_cached()
    if not metrics:
        return "⚠️ تعذّر جلب نظرة عامة على السوق حالياً."

    price = metrics["price"]
    change_pct = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    vol_score = metrics["volatility_score"]
    liq = metrics["liquidity_pulse"]
    strength = metrics["strength_label"]
    rsi = metrics["rsi_est"]

    direction = "يميل للصعود" if change_pct > 0 else "يميل للهبوط" if change_pct < 0 else "أقرب لحركة جانبية"
    sign = "+" if change_pct >= 0 else ""

    text = f"""
🌐 <b>نظرة عامة سريعة على سوق الكريبتو (BTC كمؤشر رئيسى)</b>

💰 سعر البيتكوين الآن: <b>${price:,.0f}</b>
📈 تغير 24 ساعة: <b>{sign}{change_pct:.2f}%</b>
🔁 مدى حركة اليوم: <b>{range_pct:.2f}%</b>
📊 درجة التقلب: <b>{vol_score:.1f} / 100</b>
📉 تقدير RSI العام: <b>{rsi:.1f}</b>

🧭 ملخص وضع السوق:
• الاتجاه العام: <b>{direction}</b>
• وصف الحركة: <b>{strength}</b>
• نبض السيولة: <b>{liq}</b>

IN CRYPTO Ai 🤖 — متابعة لحظية للسوق بناءً على بيانات البتكوين كمؤشر.
"""
    return text.strip()


def format_risk_test() -> str:
    metrics = get_market_metrics_cached()
    if not metrics:
        return "⚠️ تعذّر إجراء اختبار المخاطر حالياً."

    risk = evaluate_risk_level(
        metrics["change_pct"], metrics["volatility_score"]
    )

    text = f"""
🧪 <b>اختبار مخاطر السوق (IN CRYPTO Ai)</b>

• مستوى المخاطر الحالى: <b>{risk['emoji']} {_risk_level_ar(risk['level'])}</b>

📊 تفاصيل سريعة:
• تغير 24 ساعة: <b>{metrics['change_pct']:.2f}%</b>
• درجة التقلب: <b>{metrics['volatility_score']:.1f} / 100</b>
• مدى الحركة اليومى: <b>{metrics['range_pct']:.2f}%</b>

💡 توصية عامة:
{risk['message']}

هذا التقييم عام، وليس نصيحة استثمارية مباشرة.
"""
    return text.strip()


def format_weekly_ai_report() -> str:
    """
    تقرير أسبوعى مبسط يعتمد على مقاييس اليوم كنقطة تمثيل
    (عشان الخطة المجانية وبدون داتا تاريخية كاملة).
    """
    metrics = get_market_metrics_cached()
    if not metrics:
        return "⚠️ تعذّر إنشاء التقرير الأسبوعى حالياً."

    risk = evaluate_risk_level(
        metrics["change_pct"], metrics["volatility_score"]
    )

    text = f"""
📅 <b>تقرير أسبوعى مختصر من IN CRYPTO Ai</b>

💰 سعر البيتكوين الحالى: <b>${metrics['price']:,.0f}</b>
📈 تغير آخر 24 ساعة (كمؤشر لحالة الأسبوع): <b>{metrics['change_pct']:.2f}%</b>
🔁 مدى الحركة اليومى: <b>{metrics['range_pct']:.2f}%</b>
📊 درجة التقلب التقريبية: <b>{metrics['volatility_score']:.1f} / 100</b>

🧭 ملخص عام:
• وصف قوة الحركة: <b>{metrics['strength_label']}</b>
• نبض السيولة: <b>{metrics['liquidity_pulse']}</b>
• مستوى المخاطر: <b>{risk['emoji']} {_risk_level_ar(risk['level'])}</b>

🏁 توصية عامة للأسبوع:
{risk['message']}

IN CRYPTO Ai 🤖 — تقرير أسبوعى يساعدك على رؤية الصورة الكبيرة دون إهمال التفاصيل اللحظية.
"""
    return text.strip()


# =========================================================
#      رسالة التحذير الاحترافية (Smart Crash Alert)
# =========================================================

def format_ai_alert(metrics: dict | None = None, risk: dict | None = None) -> str:
    """
    يبنى رسالة تحذير كاملة عن السوق.
    لو metrics/risk مش متبعتة، بيجيبها من الكاش.
    """
    if metrics is None:
        metrics = get_market_metrics_cached()
    if not metrics:
        return "⚠️ تعذّر توليد تحذير السوق حالياً (لا توجد بيانات كافية)."

    if risk is None:
        risk = evaluate_risk_level(
            metrics["change_pct"], metrics["volatility_score"]
        )

    price = metrics["price"]
    change_pct = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    vol_score = metrics["volatility_score"]
    rsi = metrics["rsi_est"]
    liq = metrics["liquidity_pulse"]
    strength = metrics["strength_label"]
    dist_low = metrics.get("distance_from_low_pct", 0.0)

    t1, t2, drop_comment = _estimate_drop_targets(
        price, change_pct, vol_score
    )

    sign = "+" if change_pct >= 0 else ""
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    direction_line = strength
    if change_pct <= -4:
        direction_line = "هبوط قوى مع ضغوط بيعية عالية."
    elif change_pct <= -2:
        direction_line = "الاتجاه العام يميل بوضوح للهبوط مع ضغط بيعى متزايد."
    elif change_pct >= 4:
        direction_line = "صعود قوى مع دخول سيولة شرائية ملحوظة."
    elif change_pct >= 2:
        direction_line = "الاتجاه العام يميل لصعود هادئ مع تحسن تدريجى فى الزخم."

    volatility_line = (
        f"درجة التقلب الحالية: <b>{vol_score:.1f} / 100</b>"
    )

    if dist_low < 1.5 and change_pct < 0:
        near_low_line = (
            f"السعر حالياً يتحرك بالقرب من قاع اليوم (~{dist_low:.2f}% فوق الأدنى اليومى)، "
            "ما يعنى أن أى كسر إضافى قد يفتح المجال لهبوط أعمق."
        )
    else:
        near_low_line = (
            "السعر حالياً ليس عند قاع اليوم المباشر، "
            "لكن ما زالت حركة السوق متأثرة بالسيولة والتقلب."
        )

    drop_part = ""
    if t1 and t2:
        drop_part = f"""
📉 <b>أهداف هبوط تقريبية لو استمر الضغط:</b>
• منطقة دعم أولى محتملة قرب: <b>${t1:,.0f}</b>
• منطقة دعم أعمق محتملة قرب: <b>${t2:,.0f}</b>
{drop_comment}
"""

    text = f"""
⚠️ <b>تنبيه هام — السوق يدخل منطقة حساسة</b>

📅 اليوم: <b>{today_str}</b>
📉 البيتكوين الآن: <b>${price:,.0f}</b>  (تغير 24 ساعة: <b>{sign}{change_pct:.2f}%</b>)

🧭 <b>ملخص سريع لوضع السوق:</b>
• {direction_line}
• مدى حركة اليوم بالنسبة للسعر: حوالى <b>{range_pct:.2f}%</b>
• {volatility_line}
• نبض السيولة: <b>{liq}</b>
• مستوى المخاطر: <b>{risk['emoji']} {_risk_level_ar(risk['level'])}</b>

📉 <b>المؤشرات الفنية المختصرة:</b>
• قراءة RSI التقديرية: <b>{rsi:.1f}</b> → منطقة {"تشبع بيعى" if rsi < 35 else "حيادية تقريباً" if rsi < 60 else "تشبع شرائى جزئى"}
• {near_low_line}

{drop_part}
🤖 <b>خلاصة IN CRYPTO Ai (نظرة مركزة):</b>
• الاتجاه العام: <b>{strength}</b>
• سلوك السيولة: <b>{liq}</b>
• تقدير حركة 24–72 ساعة (تقريبى، غير مضمون):
  - صعود محتمل: ~<b>{max(10, 50 - abs(change_pct)):.0f}%</b>
  - تماسك جانبى: ~<b>{max(10, 40 - abs(change_pct) / 2):.0f}%</b>
  - هبوط محتمل: ~<b>{min(60, abs(change_pct) * 2 + vol_score / 3):.0f}%</b>

🏁 <b>التوصية العامة من IN CRYPTO Ai:</b>
• ركّز على حماية رأس المال أولاً قبل البحث عن الفرص.
• تجنب القرارات الانفعالية وقت الأخبار أو حركات الشموع الكبيرة.
• انتظر اختراق أو كسر واضح لمناطق السعر الرئيسية قبل أى دخول عدوانى.
• فى حالة استخدام رافعة مالية، يُفضل تقليل الرافعة قدر الإمكان حالياً.

IN CRYPTO Ai 🤖 — منظومة ذكاء اصطناعى شاملة لتحليل السوق فى الوقت الفعلى.
"""
    return text.strip()


def format_ai_alert_details() -> str:
    """
    تفاصيل إضافية يمكن عرضها للأدمن من زر "عرض التفاصيل".
    """
    m = get_market_metrics_cached()
    if not m:
        return "لا توجد بيانات كافية حالياً لعرض تفاصيل التحذير."

    risk = evaluate_risk_level(m["change_pct"], m["volatility_score"])

    text = f"""
📋 <b>تفاصيل فنية إضافية عن حالة السوق</b>

• السعر الحالى: <b>${m['price']:,.0f}</b>
• الافتتاح (24h): <b>${m['open']:,.0f}</b>
• أعلى / أدنى (24h): <b>${m['high']:,.0f}</b> / <b>${m['low']:,.0f}</b>

• تغير 24 ساعة: <b>{m['change_pct']:.2f}%</b>
• مدى الحركة (High/Low): <b>{m['range_pct']:.2f}%</b>
• المسافة عن قاع اليوم: <b>{m.get('distance_from_low_pct', 0.0):.2f}%</b>
• درجة التقلب التقريبية: <b>{m['volatility_score']:.1f} / 100</b>
• حجم التداول (BTC): <b>{m['volume']:,.0f}</b>
• حجم تداول تقديرى بالدولار: <b>${m['quote_volume']/1e9:.3f}B</b>

• قراءة RSI التقديرية: <b>{m['rsi_est']:.1f}</b>
• وصف قوة الحركة: <b>{m['strength_label']}</b>
• نبض السيولة: <b>{m['liquidity_pulse']}</b>

• مستوى المخاطر المحسوب: <b>{risk['emoji']} {_risk_level_ar(risk['level'])}</b>
• شرح المخاطر: {risk['message']}
"""
    return text.strip()
