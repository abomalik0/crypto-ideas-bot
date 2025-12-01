# analysis_engine.py
import math
import time
from datetime import datetime

import requests

import config

HTTP = config.HTTP_SESSION

BINANCE_BASE = "https://api.binance.com"
KUCOIN_BASE = "https://api.kucoin.com"


# ==============================
#  Helpers: Fetch Ticker Data
# ==============================

def _fetch_binance_24h(symbol: str) -> dict | None:
    try:
        r = HTTP.get(
            f"{BINANCE_BASE}/api/v3/ticker/24hr",
            params={"symbol": symbol.upper()},
            timeout=10,
        )
        if r.status_code == 400:
            # invalid symbol
            config.API_STATUS["binance_ok"] = False
            return None
        r.raise_for_status()
        data = r.json()
        config.API_STATUS["binance_ok"] = True
        config.API_STATUS["last_api_check"] = datetime.utcnow().isoformat(timespec="seconds")
        return data
    except Exception as e:
        config.logger.warning("Binance error for %s: %s", symbol, e)
        config.API_STATUS["binance_ok"] = False
        return None


def _fetch_kucoin_24h(symbol: str) -> dict | None:
    """
    KuCoin إسم الزوج بيكون مثلاً BTC-USDT
    """
    try:
        if symbol.upper().endswith("USDT"):
            base = symbol.upper().replace("USDT", "")
            pair = f"{base}-USDT"
        else:
            pair = symbol.upper()

        r = HTTP.get(
            f"{KUCOIN_BASE}/api/v1/market/stats",
            params={"symbol": pair},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "200000":
            raise RuntimeError(f"KuCoin returned code {data.get('code')}")
        stats = data.get("data") or {}
        config.API_STATUS["kucoin_ok"] = True
        config.API_STATUS["last_api_check"] = datetime.utcnow().isoformat(timespec="seconds")
        return {
            "lastPrice": stats.get("last"),
            "priceChangePercent": stats.get("changeRate", 0) * 100 if stats.get("changeRate") is not None else 0,
            "highPrice": stats.get("high"),
            "lowPrice": stats.get("low"),
        }
    except Exception as e:
        config.logger.warning("KuCoin error for %s: %s", symbol, e)
        config.API_STATUS["kucoin_ok"] = False
        return None


# ==============================
#  Metrics Builder
# ==============================

def _safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def get_symbol_metrics(symbol: str) -> dict | None:
    """
    يرجع:
    {
        price,
        change_pct,
        range_pct,
        volatility_score (0–100),
        strength_label,
        liquidity_pulse,
        rsi_estimate
    }
    """
    data = _fetch_binance_24h(symbol)
    if not data:
        data = _fetch_kucoin_24h(symbol)
        if not data:
            return None

    price = _safe_float(data.get("lastPrice") or data.get("last"))
    change_pct = _safe_float(data.get("priceChangePercent"))
    high = _safe_float(data.get("highPrice") or data.get("high"))
    low = _safe_float(data.get("lowPrice") or data.get("low"))

    if price <= 0 or high <= 0 or low <= 0:
        return None

    day_range = high - low
    range_pct = (day_range / price) * 100 if price else 0

    # تقدير بسيط للتقلب (0–100)
    volatility_score = max(0.0, min(100.0, range_pct * 3.2))

    # تقدير RSI بسيط من التغير اليومى
    rsi_est = 50 + (change_pct * 4)
    if rsi_est < 5:
        rsi_est = 5
    if rsi_est > 95:
        rsi_est = 95

    # قوة السوق
    strength_label = _build_strength_label(change_pct, volatility_score, range_pct)
    liquidity_pulse = _build_liquidity_pulse(change_pct, volatility_score)

    return {
        "symbol": symbol.upper(),
        "price": price,
        "change_pct": change_pct,
        "range_pct": range_pct,
        "volatility_score": volatility_score,
        "strength_label": strength_label,
        "liquidity_pulse": liquidity_pulse,
        "rsi_estimate": rsi_est,
        "high": high,
        "low": low,
    }


def _build_strength_label(change_pct: float, vol: float, rng: float) -> str:
    abs_c = abs(change_pct)
    if abs_c < 0.5 and vol < 20:
        return "سوق هادئ / حركة جانبية ضعيفة"
    if change_pct >= 0.5 and change_pct < 2 and vol < 50:
        return "اتجاه صاعد هادئ"
    if change_pct >= 2 and vol < 70:
        return "اتجاه صاعد واضح مع زخم صحى"
    if change_pct >= 3 and vol >= 70:
        return "صعود حاد مع تقلبات قوية — منطقة خطر للمطاردة"
    if change_pct <= -0.5 and change_pct > -2 and vol < 50:
        return "هبوط هادئ / تصحيح طبيعى"
    if change_pct <= -2 and vol < 70:
        return "ضغط بيعى واضح مع اتجاه هابط"
    if change_pct <= -3 and vol >= 70:
        return "بيع عنيف / ذعر محتمل — توخى الحذر"
    return "تذبذب نشط بدون اتجاه حاسم"


def _build_liquidity_pulse(change_pct: float, vol: float) -> str:
    if abs(change_pct) < 0.3 and vol < 20:
        return "السيولة خفيفة — اهتمام ضعيف من المشترين والبائعين."
    if change_pct >= 0.8:
        return "السيولة تميل لصالح المشترين مع ضغط شرائى متزايد."
    if change_pct <= -0.8:
        return "السيولة تميل لصالح البائعين مع ضغط بيعى واضح."
    if vol > 60 and abs(change_pct) < 1.0:
        return "تذبذب عالى مع تناوب سريع بين المشترين والبائعين."
    return "السيولة متوازنة تقريباً بين المشترين والبائعين."


# ==============================
#     Market Metrics Cache
# ==============================

def get_market_metrics_cached() -> dict | None:
    """بيانات BTC للسوق / Dashboard مع كاش."""
    now = time.time()
    cached = config.MARKET_METRICS_CACHE.get("data")
    ts = config.MARKET_METRICS_CACHE.get("ts") or 0.0

    if cached and (now - ts) <= config.MARKET_METRICS_TTL_SECONDS:
        return cached

    metrics = get_symbol_metrics("BTCUSDT")
    if metrics:
        config.MARKET_METRICS_CACHE["data"] = metrics
        config.MARKET_METRICS_CACHE["ts"] = now
        return metrics

    return cached  # لو فشل و فى كاش قديم نرجعه بدل لا شىء


# ==============================
#       تقييم المخاطر
# ==============================

def evaluate_risk_level(change_pct: float, vol_score: float) -> dict:
    """
    يرجع:
    {
        "level": "low"/"medium"/"high",
        "emoji": "🟢/🟡/🔴",
        "message": "..."
    }
    """
    abs_c = abs(change_pct)

    # Low risk
    if abs_c < 1.0 and vol_score < 25:
        return {
            "level": "low",
            "emoji": "🟢",
            "message": "المخاطر العامة منخفضة؛ السوق يتحرك بهدوء نسبى.",
        }

    # Medium
    if abs_c < 3.0 and vol_score < 60:
        return {
            "level": "medium",
            "emoji": "🟡",
            "message": "مستوى مخاطر متوسط؛ حركة مقبولة لكن تحتاج إدارة مركز ووقف خسارة.",
        }

    # High
    return {
        "level": "high",
        "emoji": "🔴",
        "message": "مستوى مخاطر عالى؛ تقلبات قوية واحتمال حركات عنيفة فى وقت قصير.",
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
#   منطق شروط التحذير الذكى
# ==============================

def detect_alert_condition(metrics: dict, risk: dict) -> str | None:
    """
    يرجع سبب نصى للتحذير أو None:
      - extreme_dump
      - extreme_pump
      - high_volatility
      - drift_with_stress
    """
    c = metrics["change_pct"]
    vol = metrics["volatility_score"]
    rng = metrics["range_pct"]

    # ذعر هبوط قوى
    if c <= -5 and vol >= 60:
        return "extreme_dump"

    # Pump عنيف
    if c >= 5 and vol >= 60:
        return "extreme_pump"

    # تقلب عالى بدون اتجاه واضح
    if abs(c) < 1.0 and vol >= 70 and rng >= 7:
        return "high_volatility"

    # Drift (حركة بطيئة لكن مستمرة + توتر)
    if abs(c) >= 2.5 and vol >= 40:
        return "drift_with_stress"

    # لو Engine شايف High Risk بدون شروط فوق
    if risk["level"] == "high":
        return "risk_engine_high"

    return None


# ==============================
#   فورمات رسائل التحليل العادية
# ==============================

def _fmt_price(num: float) -> str:
    return f"{num:,.2f}".replace(",", " ")


def format_analysis(symbol: str) -> str:
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol = symbol + "USDT"

    m = get_symbol_metrics(symbol)
    if not m:
        return (
            f"❌ تعذر جلب بيانات <b>{symbol}</b> الآن.\n"
            "حاول مرة أخرى بعد قليل أو جرّب عملة أخرى."
        )

    price = _fmt_price(m["price"])
    c = m["change_pct"]
    rng = m["range_pct"]
    vol = m["volatility_score"]
    rsi = m["rsi_estimate"]

    sign = "+" if c >= 0 else ""
    risk = evaluate_risk_level(c, vol)

    return f"""
<b>تحليل سريع لـ {symbol}</b>

💰 السعر الآن: <b>${price}</b>
📊 التغير خلال 24 ساعة: <b>{sign}{c:.2f}%</b>
📌 مدى حركة اليوم: <b>{rng:.2f}%</b>
🌪 درجة التقلب: <b>{vol:.1f} / 100</b>
📈 تقدير RSI: <b>{rsi:.1f}</b>

🧭 <b>قوة السوق:</b>
• {m["strength_label"]}
• نبض السيولة: {m["liquidity_pulse"]}

🛡 <b>مستوى المخاطر العام:</b>
• {risk["emoji"]} {_risk_level_ar(risk["level"])} — {risk["message"]}

IN CRYPTO Ai 🤖 — قراءة تعليمية وليست توصية مباشرة بالشراء أو البيع.
""".strip()


def format_market_report() -> str:
    m = get_market_metrics_cached()
    if not m:
        return "❌ تعذر توليد تقرير السوق الآن، مشكلة فى مزود البيانات."

    price = _fmt_price(m["price"])
    c = m["change_pct"]
    rng = m["range_pct"]
    vol = m["volatility_score"]
    risk = evaluate_risk_level(c, vol)

    sign = "+" if c >= 0 else ""
    return f"""
<b>IN CRYPTO Ai — نظرة عامة على سوق البيتكوين</b>

💰 السعر الحالى: <b>${price}</b>
📊 تغير آخر 24 ساعة: <b>{sign}{c:.2f}%</b>
📌 مدى حركة اليوم: <b>{rng:.2f}%</b>
🌪 درجة التقلب: <b>{vol:.1f} / 100</b>

🧭 <b>قوة السوق:</b>
• {m["strength_label"]}
• نبض السيولة: {m["liquidity_pulse"]}

🛡 <b>مستوى المخاطر:</b>
• {risk["emoji"]} {_risk_level_ar(risk["level"])} — {risk["message"]}

⏱ هذه القراءة تعتمد فقط على بيانات BTCUSDT من Binance/KuCoin.
""".strip()


def format_risk_test() -> str:
    m = get_market_metrics_cached()
    if not m:
        return "❌ تعذر تنفيذ اختبار المخاطر الآن."

    risk = evaluate_risk_level(m["change_pct"], m["volatility_score"])
    lvl = _risk_level_ar(risk["level"])

    return f"""
<b>اختبار المخاطر السريع — IN CRYPTO Ai</b>

📌 مستوى المخاطر الحالى: {risk["emoji"]} <b>{lvl}</b>

شرح مبسط:
{risk["message"]}

📊 الأساس:
• تغير 24 ساعة: {m["change_pct"]:+.2f}%
• درجة التقلب: {m["volatility_score"]:.1f} / 100
• مدى اليوم: {m["range_pct"]:.2f}%

🎯 التوصية العامة:
• اتحكم فى حجم العقد.
• استخدم وقف خسارة واضح.
• تجنب الدخول وقت الأخبار الكبيرة دون خطة.
""".strip()


def format_weekly_ai_report() -> str:
    m = get_market_metrics_cached()
    if not m:
        return "📅 التقرير الأسبوعى: لا توجد بيانات كافية الآن."

    c = m["change_pct"]
    vol = m["volatility_score"]
    rng = m["range_pct"]
    risk = evaluate_risk_level(c, vol)

    sign = "+" if c >= 0 else ""
    today = datetime.utcnow().strftime("%Y-%m-%d")

    return f"""
📅 <b>تقرير أسبوعى — IN CRYPTO Ai</b>
اليوم: <b>{today}</b>

📊 ملخص البيتكوين (بناء على آخر 24 ساعة):
• التغير اليومى: <b>{sign}{c:.2f}%</b>
• مدى الحركة: <b>{rng:.2f}%</b>
• درجة التقلب: <b>{vol:.1f} / 100</b>

🧭 قوة السوق:
• {m["strength_label"]}
• نبض السيولة: {m["liquidity_pulse"]}

🛡 مستوى المخاطر:
• {risk["emoji"]} {_risk_level_ar(risk["level"])} — {risk["message"]}

🎯 ملاحظات IN CRYPTO Ai للأيام القادمة:
• ركّز على حماية رأس المال قبل أى شيء.
• أفضل الفرص عادةً تظهر بعد الحركات العنيفة، وليس أثناء الذروة.
• احترم وقف الخسارة مهما كان شعورك تجاه الصفقة.

هذا التقرير تعليمى، وليس توصية مالية مباشرة.
""".strip()


# ==============================
#      فورمات رسالة التحذير
# ==============================

def _classify_scenario_prob(change_pct: float, vol: float, rng: float):
    """
    تقدير تقريبى لاحتمالات:
    - صعود
    - تماسك
    - هبوط
    (بس عشان نملأ الجزء الإحصائى فى التحذير)
    """
    up = 33.0
    down = 33.0
    side = 34.0

    if change_pct > 0:
        up += abs(change_pct) * 3
        down -= abs(change_pct) * 2
    elif change_pct < 0:
        down += abs(change_pct) * 3
        up -= abs(change_pct) * 2

    if vol < 20:
        side += 10
        up -= 5
        down -= 5
    elif vol > 60:
        side -= 10
        up += 5
        down += 5

    tot = max(up + down + side, 1.0)
    up = max(0.0, min(100.0, up / tot * 100))
    down = max(0.0, min(100.0, down / tot * 100))
    side = max(0.0, min(100.0, side / tot * 100))

    # نطبع تقريبا 30/55/15 زى المثال
    return round(up), round(side), round(down)


def _build_alert_headline(reason: str, risk: dict) -> str:
    if reason == "extreme_dump":
        return "🚨 تحذير قوى — ضغط بيعى حاد على السوق"
    if reason == "extreme_pump":
        return "🚨 تحذير قوى — صعود حاد واحتمال تقلبات عنيفة"
    if reason == "high_volatility":
        return "⚠️ تنبيه هام — تقلب مرتفع بدون اتجاه واضح"
    if reason == "drift_with_stress":
        return "⚠️ تنبيه هام — حركة قوية مع توتر متزايد فى السوق"
    if reason == "risk_engine_high":
        return f"⚠️ تنبيه من Engine المخاطر ({risk['emoji']})"
    return "⚠️ تنبيه هام — السوق يدخل منطقة حساسة"


def format_ai_alert() -> str:
    """
    الرسالة الأساسية اللى تبعت للأدمن / التحذير التلقائى.
    مدموج فيها أسلوب الرسالة اللى انت بعته قبل كده.
    """
    m = get_market_metrics_cached()
    if not m:
        return "⚠️ تعذر توليد تنبيه لأن بيانات السوق غير متاحة حالياً."

    c = m["change_pct"]
    vol = m["volatility_score"]
    rng = m["range_pct"]
    price = _fmt_price(m["price"])
    today = datetime.utcnow().strftime("%Y-%m-%d")
    sign = "+" if c >= 0 else ""
    risk = evaluate_risk_level(c, vol)

    reason = detect_alert_condition(m, risk)
    headline = _build_alert_headline(reason or "", risk)

    # RSI / ملخص فنى بسيط
    rsi = m["rsi_estimate"]

    up_p, side_p, down_p = _classify_scenario_prob(c, vol, rng)

    body = f"""
{headline}

📅 اليوم: {today}
📉 البيتكوين الآن: <b>${price}</b>  (تغير 24 ساعة: <b>{sign}{c:.2f}%</b>)

🧭 <b>ملخص سريع لوضع السوق:</b>
• {m["strength_label"]}
• نبض السيولة: {m["liquidity_pulse"]}
• مدى حركة اليوم بالنسبة للسعر: حوالى <b>{rng:.2f}%</b>
• درجة التقلب الحالية: <b>{vol:.1f} / 100</b>
• مستوى المخاطر: {risk["emoji"]} {_risk_level_ar(risk["level"])}

📉 <b>المؤشرات الفنية المختصرة:</b>
• قراءة RSI التقديرية: <b>{rsi:.1f}</b> → منطقة حيادية تقريبياً
• السعر يتحرك داخل نطاق يومى متذبذب.
• لا توجد إشارة انعكاس مكتملة حتى الآن، لكن الزخم يتغير بسرعة مع الأخبار والسيولة.

⚡️ <b>منظور مضارِبى (قصير المدى):</b>
• يُفضّل استخدام أحجام عقود صغيرة مع وقف خسارة واضح.
• تجنب مطاردة الشموع الكبيرة؛ استنى إعادة الاختبار لمناطق واضحة.

💎 <b>منظور استثمارى (مدى متوسط):</b>
• اعتبر إن الوضع الحالى أشبه بمرحلة إعادة تمركز؛
  القرارات الكبيرة يُفضّل أن تكون على مستويات سعرية أوضح، وليس فى قلب التقلب.

🤖 <b>خلاصة IN CRYPTO Ai (نظرة مركزة):</b>
• الاتجاه العام: {m["strength_label"]}
• سلوك السيولة: {m["liquidity_pulse"]}
• تقييم المخاطر: {risk["emoji"]} {_risk_level_ar(risk["level"])} — {risk["message"]}

📌 <b>تقدير حركة 24–72 ساعة:</b>
  - صعود محتمل: ~{up_p}%
  - تماسك جانبى: ~{side_p}%
  - هبوط محتمل: ~{down_p}%

🏁 <b>التوصية العامة من IN CRYPTO Ai:</b>
• ركّز على حماية رأس المال أولاً قبل البحث عن الفرص.
• تجنب القرارات الانفعالية وقت الأخبار أو حركات الشموع الكبيرة.
• انتظر اختراق أو كسر واضح لمناطق السعر الرئيسية قبل أى دخول عدوانى.

IN CRYPTO Ai 🤖 — منظومة ذكاء اصطناعى لمراقبة السوق فى الوقت الفعلى.
هذه الرسالة تعليمية، وليست نصيحة استثمارية مباشرة.
""".strip()

    return body


def format_ai_alert_details() -> str:
    """
    تفاصيل إضافية تظهر عند الضغط على زر "عرض التفاصيل" فى لوحة التحكم أو /alert.
    """
    m = get_market_metrics_cached()
    if not m:
        return "لا توجد بيانات تفصيلية حالياً."

    c = m["change_pct"]
    rng = m["range_pct"]
    vol = m["volatility_score"]
    rsi = m["rsi_estimate"]
    risk = evaluate_risk_level(c, vol)

    return f"""
<b>تفاصيل Alert IN CRYPTO Ai</b>

• السعر: ${_fmt_price(m["price"])}
• تغير 24 ساعة: {c:+.2f}%
• مدى اليوم: {rng:.2f}%
• درجة التقلب: {vol:.1f} / 100
• تقدير RSI: {rsi:.1f}

• قوة السوق: {m["strength_label"]}
• نبض السيولة: {m["liquidity_pulse"]}
• مستوى المخاطر: {risk["emoji"]} {_risk_level_ar(risk["level"])} — {risk["message"]}

هذه المعطيات هى نفس الأساس الذى يعتمد عليه نظام التحذير التلقائى.
""".strip()
