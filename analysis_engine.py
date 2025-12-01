import math
import time
from datetime import datetime, timezone

import requests

import config

HTTP = config.HTTP_SESSION

BINANCE_API = "https://api.binance.com/api/v3"
KUCOIN_API = "https://api.kucoin.com/api/v1"


# ==============================
#   Helpers
# ==============================


def _to_float(v, default=None):
    try:
        return float(v)
    except Exception:
        return default


def _weekday_ar(dt: datetime) -> str:
    names = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    # فى بايثون Monday=0
    return names[dt.weekday()]


def _format_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.0f}"
    return f"{p:,.2f}"


def _safe_percent(a, b):
    if not b:
        return 0.0
    return (a / b) * 100.0


# ==============================
#   جلب بيانات السوق
# ==============================


def _fetch_binance_ticker(symbol: str):
    try:
        r = HTTP.get(f"{BINANCE_API}/ticker/24hr", params={"symbol": symbol}, timeout=5)
        r.raise_for_status()
        data = r.json()
        return {
            "price": _to_float(data.get("lastPrice")),
            "high": _to_float(data.get("highPrice")),
            "low": _to_float(data.get("lowPrice")),
            "volume": _to_float(data.get("volume")),
            "price_change_pct": _to_float(data.get("priceChangePercent")),
        }
    except Exception as e:
        config.logger.exception("Binance ticker error for %s: %s", symbol, e)
        config.API_STATUS["binance_ok"] = False
        config.API_STATUS["last_error"] = str(e)
        return None


def _fetch_kucoin_ticker(symbol: str):
    # KuCoin تستخدم BTC-USDT
    if symbol.endswith("USDT"):
        s = symbol.replace("USDT", "-USDT")
    else:
        s = symbol
    try:
        r = HTTP.get(f"{KUCOIN_API}/market/stats", params={"symbol": s}, timeout=5)
        r.raise_for_status()
        d = r.json().get("data") or {}
        return {
            "price": _to_float(d.get("last")),
            "high": _to_float(d.get("high")),
            "low": _to_float(d.get("low")),
            "volume": _to_float(d.get("vol")),
            "price_change_pct": _to_float(d.get("changeRate")) * 100.0
            if d.get("changeRate") is not None
            else None,
        }
    except Exception as e:
        config.logger.exception("KuCoin ticker error for %s: %s", symbol, e)
        config.API_STATUS["kucoin_ok"] = False
        config.API_STATUS["last_error"] = str(e)
        return None


def _merge_tickers(primary, secondary):
    if primary:
        return primary
    return secondary


def _rough_rsi(change_pct_24h: float, range_pct: float) -> float:
    """
    تقدير تقريبى لـ RSI من غير بيانات كاملة.
    """
    base = 50.0 + change_pct_24h * 1.2
    base += (range_pct - 3) * 0.3
    return max(0.0, min(100.0, base))


def _rough_volatility(range_pct: float, volume: float) -> float:
    """
    درجة تقلب من 0 إلى 100 بشكل تقريبى.
    """
    vol_score = min(range_pct * 4.0, 60.0)
    if volume:
        vol_score += min(math.log10(volume + 1) * 3.0, 40.0)
    return max(0.0, min(100.0, vol_score))


def _rough_liquidity(price: float, volume: float, change_pct: float) -> float:
    """
    مؤشر بسيط بين -1 و +1:
    -1 = خروج سيولة عنيف، +1 = دخول سيولة قوى.
    """
    if not price or not volume:
        return 0.0
    pulse = math.tanh(change_pct / 5.0) * 0.6 + math.tanh(volume / 1e9) * 0.4
    return max(-1.0, min(1.0, pulse))


def get_market_metrics(symbol="BTCUSDT"):
    """
    يرجّع dict فيها كل المقاييس المستخدمة فى التحليل والتحذيرات.
    """
    cache = config.MARKET_METRICS_CACHE
    now = time.time()
    if (
        cache.get("symbol") == symbol
        and cache.get("ts")
        and now - cache["ts"] < config.MARKET_TTL_SECONDS
    ):
        return cache

    binance = _fetch_binance_ticker(symbol)
    kucoin = _fetch_kucoin_ticker(symbol)

    merged = _merge_tickers(binance, kucoin)
    if not merged:
        return None

    price = merged["price"]
    high = merged["high"]
    low = merged["low"]
    volume = merged["volume"]
    change_pct = merged["price_change_pct"]

    if not all([price, high, low]):
        return None

    range_pct = _safe_percent(high - low, price)
    rsi_est = _rough_rsi(change_pct, range_pct)
    volatility = _rough_volatility(range_pct, volume)
    liquidity = _rough_liquidity(price, volume, change_pct)

    # مستويات دعم/مقاومة تقريبية (كفاية للتحذيرات)
    support_1 = low * 0.995
    resistance_1 = high * 1.005
    deep_support = low * 0.97  # دعم عميق محتمل
    breakout_level = high * 1.03

    strength_label = "محايد"
    if change_pct >= 4 and volatility >= 25:
        strength_label = "صعود قوى"
    elif change_pct <= -4 and volatility >= 25:
        strength_label = "هبوط قوى"
    elif abs(change_pct) < 2 and range_pct < 3:
        strength_label = "حركة هادئة"

    metrics = {
        "symbol": symbol,
        "ts": now,
        "price": price,
        "high": high,
        "low": low,
        "volume": volume,
        "change_pct": change_pct,
        "range_pct": range_pct,
        "volatility_score": volatility,
        "rsi_est": rsi_est,
        "liquidity_pulse": liquidity,
        "support_1": support_1,
        "resistance_1": resistance_1,
        "deep_support": deep_support,
        "breakout_level": breakout_level,
        "strength_label": strength_label,
    }

    config.MARKET_METRICS_CACHE.update(metrics)
    config.API_STATUS["binance_ok"] = binance is not None
    config.API_STATUS["kucoin_ok"] = kucoin is not None
    config.API_STATUS["last_api_check"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )

    return metrics


def get_market_metrics_cached():
    return get_market_metrics("BTCUSDT")


# ==============================
#   تقييم مستوى المخاطر
# ==============================


def evaluate_risk_level(change_pct: float, volatility_score: float):
    """
    يرجّع dict: { level: low/medium/high/extreme, emoji, message }
    """
    level = "low"
    if change_pct is None:
        return {"level": "unknown", "emoji": "❔", "message": "بيانات غير مكتملة."}

    abs_change = abs(change_pct)

    if abs_change < 2 and volatility_score < 10:
        level = "low"
    elif abs_change < 4 and volatility_score < 20:
        level = "medium"
    elif abs_change < 7 or volatility_score < 35:
        level = "high"
    else:
        level = "extreme"

    if change_pct <= -5 and volatility_score >= 20:
        level = "high"
    if change_pct <= -8 or (change_pct <= -6 and volatility_score >= 35):
        level = "extreme"

    emoji = {
        "low": "🟢",
        "medium": "🟡",
        "high": "🟠",
        "extreme": "🔴",
    }.get(level, "❔")

    msg = {
        "low": "المخاطر منخفضة نسبيًا، الحركة أقرب لهدوء أو تذبذب محدود.",
        "medium": "مستوى مخاطر متوسط، السوق يتحرك لكن بدون عنف شديد.",
        "high": "مخاطر مرتفعة، الحركة قوية وقد تكون مصحوبة بذعر أو FOMO.",
        "extreme": "خطر عالى جدًا / Panic ممكن يؤدى لحركات عنيفة فى وقت قصير.",
    }.get(level, "غير محدد.")

    return {"level": level, "emoji": emoji, "message": msg}


def _risk_level_ar(level: str) -> str:
    mapping = {
        "low": "منخفض",
        "medium": "متوسط",
        "high": "مرتفع",
        "extreme": "خطير جدًا",
        "unknown": "غير معروف",
    }
    return mapping.get(level, "غير معروف")


# ==============================
#   منطق اكتشاف التحذير
# ==============================


def detect_alert_condition(metrics: dict, risk: dict | None):
    """
    يحدد هل فى سبب قوى لإرسال تحذير أم لا.
    يرجّع كود نصى بسيط:
        None = لا يوجد تحذير
        "strong_dump" = هبوط حاد
        "panic_sell" = بيع عنيف / Panic
        "vol_spike" = تقلب عالى مع خروج سيولة
    """
    if not metrics:
        return None

    change_pct = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    vol = metrics["volatility_score"]
    liq = metrics["liquidity_pulse"]
    rsi = metrics["rsi_est"]

    # هبوط حاد لكن لسه مش Panic
    if change_pct <= -4 and range_pct >= 4 and vol >= 12:
        reason = "strong_dump"
    else:
        reason = None

    # Panic واضح
    if change_pct <= -7 or (change_pct <= -5 and vol >= 25 and liq < -0.2):
        reason = "panic_sell"

    # تقلب عالى وخروج سيولة حتى لو التغير مش ضخم جدًا
    if vol >= 30 and liq <= -0.4 and change_pct <= -3:
        reason = "vol_spike"

    # لو RSI أصلاً منخفض جدًا نخفف حدة التحذير
    if rsi <= 25 and change_pct > -6:
        if reason == "panic_sell":
            reason = "strong_dump"

    return reason


# ==============================
#   تنسيقات التقارير النصية
# ==============================


def format_analysis(symbol: str) -> str:
    symbol = symbol.upper()
    if not symbol.endswith("USDT"):
        symbol += "USDT"

    metrics = get_market_metrics(symbol)
    if not metrics:
        return "⚠️ تعذر جلب بيانات السوق حالياً، حاول مرة أخرى."

    price = metrics["price"]
    change_pct = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    vol = metrics["volatility_score"]
    rsi = metrics["rsi_est"]
    liq = metrics["liquidity_pulse"]

    risk = evaluate_risk_level(change_pct, vol)

    direction = "صاعد" if change_pct >= 0 else "هابط"
    dir_emoji = "📈" if change_pct >= 0 else "📉"

    text = f"""
{dir_emoji} <b>تحليل سريع لـ {symbol}</b>

• السعر الآن: <b>${_format_price(price)}</b>
• تغير 24 ساعة: <b>{change_pct:.2f}%</b>
• مدى حركة اليوم: <b>{range_pct:.2f}%</b>
• درجة التقلب: <b>{vol:.1f} / 100</b>
• تقدير RSI: <b>{rsi:.1f}</b>
• نبض السيولة: <b>{liq:.2f}</b>

• اتجاه اليوم: <b>{direction}</b>
• قوة الحركة: <b>{metrics["strength_label"]}</b>
• مستوى المخاطر: {risk["emoji"]} <b>{_risk_level_ar(risk["level"])}</b>

⚠️ هذا التحليل تعليمى ولا يعتبر نصيحة استثمارية.
"""
    return text.strip()


def format_market_report() -> str:
    metrics = get_market_metrics_cached()
    if not metrics:
        return "⚠️ تعذر جلب بيانات البيتكوين حالياً."

    price = metrics["price"]
    change_pct = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    vol = metrics["volatility_score"]
    rsi = metrics["rsi_est"]
    liq = metrics["liquidity_pulse"]
    support = metrics["support_1"]
    resistance = metrics["resistance_1"]

    risk = evaluate_risk_level(change_pct, vol)

    direction = "صعود هادئ" if change_pct >= 0 else "ضغط بيعى"
    if abs(change_pct) >= 4:
        direction = "صعود قوى" if change_pct > 0 else "هبوط قوى"

    text = f"""
🌍 <b>نظرة عامة على سوق البيتكوين</b>

• السعر الحالى: <b>${_format_price(price)}</b>
• تغير 24 ساعة: <b>{change_pct:.2f}%</b>
• مدى الحركة اليوم: <b>{range_pct:.2f}%</b>
• درجة التقلب التقديرية: <b>{vol:.1f} / 100</b>
• تقدير RSI: <b>{rsi:.1f}</b>
• نبض السيولة (تقريبى): <b>{liq:.2f}</b>

• الاتجاه اليومى الغالب: <b>{direction}</b>
• قوة الحركة الحالية: <b>{metrics["strength_label"]}</b>
• مستوى المخاطر العام: {risk["emoji"]} <b>{_risk_level_ar(risk["level"])}</b>

• دعم قصير المدى تقريبى: <b>{_format_price(support)}$</b>
• مقاومة قريبة تقريبية: <b>{_format_price(resistance)}$</b>

⚠️ لا تعتبر هذه المعلومات نصيحة بيع أو شراء، وإنما قراءة ذكية للحركة الحالية.
"""
    return text.strip()


def format_risk_test() -> str:
    metrics = get_market_metrics_cached()
    if not metrics:
        return "⚠️ لا يمكن إجراء اختبار المخاطر حالياً (بيانات غير متاحة)."

    risk = evaluate_risk_level(
        metrics["change_pct"], metrics["volatility_score"]
    )

    text = f"""
🧪 <b>اختبار حالة المخاطر الحالية</b>

• التغير 24 ساعة: <b>{metrics["change_pct"]:.2f}%</b>
• درجة التقلب: <b>{metrics["volatility_score"]:.1f} / 100</b>
• قراءة RSI تقديرية: <b>{metrics["rsi_est"]:.1f}</b>

• تقييم الذكاء الاصطناعى للمخاطر:
  → {risk["emoji"]} <b>{_risk_level_ar(risk["level"])}</b>
  → {risk["message"]}

⚠️ الهدف من هذا الاختبار هو توعية المتداول بالمخاطر، وليس تقديم توصيات مباشرة.
"""
    return text.strip()


def format_weekly_ai_report() -> str:
    metrics = get_market_metrics_cached()
    if not metrics:
        return "⚠️ لا يوجد تقرير أسبوعى حالياً بسبب نقص البيانات."

    risk = evaluate_risk_level(
        metrics["change_pct"], metrics["volatility_score"]
    )

    text = f"""
📊 <b>تقرير أسبوعى مختصر من IN CRYPTO Ai</b>

• السعر الحالى للبيتكوين: <b>${_format_price(metrics["price"])}</b>
• حركة هذا الأسبوع تقديرياً عبر نطاق اليوم: <b>{metrics["range_pct"]:.2f}%</b>
• متوسط درجة التقلب الحالية: <b>{metrics["volatility_score"]:.1f} / 100</b>

• قراءة تقريبية لمستوى المخاطر الأسبوعى:
  → {risk["emoji"]} <b>{_risk_level_ar(risk["level"])}</b>
  → {risk["message"]}

هذا التقرير يهدف لتكوين صورة أوسع عن وضع السوق، وليس توصية استثمارية مباشرة.
"""
    return text.strip()


# ==============================
#   قالب التحذير الإحترافى
# ==============================


def _build_downside_targets(metrics: dict):
    """
    يحدد منطقتين محتملتين لهدف الهبوط:
    - target1: قرب الدعم الحالى / دعم قصير
    - target2: دعم عميق محتمل (سيناريو أسوأ)
    """
    price = metrics["price"]
    support = metrics["support_1"]
    deep_support = metrics["deep_support"]

    # لو السعر أصلاً قريب من الدعم نوسع النطاق شوية
    if price - support < price * 0.02:
        target1 = support * 0.995
    else:
        target1 = support

    target2 = deep_support
    return target1, target2


def format_ai_alert(metrics=None, risk=None, reason: str | None = None) -> str:
    """
    يبنى رسالة تحذير متكاملة بالعربى.
    لو metrics/risk مش مبعوتين، هيتحسبوا تلقائياً.
    """
    if metrics is None:
        metrics = get_market_metrics_cached()
    if not metrics:
        return "⚠️ تعذر بناء تحذير السوق حالياً بسبب نقص البيانات."

    if risk is None:
        risk = evaluate_risk_level(
            metrics["change_pct"], metrics["volatility_score"]
        )

    if reason is None:
        reason = detect_alert_condition(metrics, risk)

    now = datetime.utcnow()
    weekday = _weekday_ar(now)
    today_str = now.strftime("%Y-%m-%d")

    price = metrics["price"]
    change_pct = metrics["change_pct"]
    range_pct = metrics["range_pct"]
    vol = metrics["volatility_score"]
    rsi = metrics["rsi_est"]
    liq = metrics["liquidity_pulse"]
    support = metrics["support_1"]
    resistance = metrics["resistance_1"]

    target1, target2 = _build_downside_targets(metrics)

    # وصف سريع للحالة
    if change_pct <= -5 and vol >= 20:
        short_summary = "الاتجاه العام يميل بوضوح للهبوط مع ضغط بيعى متزايد."
        micro_trend = "هبوط قوى مع ضغوط بيعية عالية."
    elif change_pct <= -3:
        short_summary = "الاتجاه يميل للهبوط مع بروز سيطرة البائعين."
        micro_trend = "هبوط ملحوظ لكن ليس Panic كامل حتى الآن."
    else:
        short_summary = "الاتجاه يتحسن تدريجيًا لكن بدون زخم صاعد قوى بعد."
        micro_trend = "حركة متذبذبة بدون اتجاه واضح."

    # وصف نبض السيولة
    if liq <= -0.4:
        liq_text = "خروج سيولة واضح مع هبوط ملحوظ."
    elif liq <= -0.15:
        liq_text = "ميول بسيطة لخروج السيولة."
    elif liq >= 0.3:
        liq_text = "دخول سيولة ملحوظ مع نشاط شرائى."
    else:
        liq_text = "السيولة متوازنة تقريباً بين المشترين والبائعين."

    # توصيف المرحلة الاستثمارية
    if reason == "panic_sell":
        phase = "مرحلة Panic / تصفية سريعة بعد كسر مستويات دعم مهمة."
    elif reason == "strong_dump":
        phase = "مرحلة بيع عنيف أو ذعر جزئى فى السوق."
    elif reason == "vol_spike":
        phase = "مرحلة تقلب عالى مع خروج سيولة ملحوظ."
    else:
        phase = "المرحلة الحالية تشبه Range / إعادة تجميع جانبى."

    # تقدير احتمالات تقريبية للحركة القادمة
    if reason in ("panic_sell", "strong_dump"):
        p_drop = 35
        p_side = 40
        p_up = 25
    elif reason == "vol_spike":
        p_drop = 30
        p_side = 45
        p_up = 25
    else:
        p_drop = 20
        p_side = 55
        p_up = 25

    text = f"""
⚠️ <b>تنبيه هام — السوق يدخل منطقة حساسة</b>

📅 اليوم: <b>{weekday}</b> — <code>{today_str}</code>
📉 البيتكوين الآن: <b>${_format_price(price)}</b>  (تغير 24 ساعة: <b>{change_pct:.2f}%</b>)

🧭 <b>ملخص سريع لوضع السوق:</b>
• {short_summary}
• {micro_trend}
• مدى حركة اليوم بالنسبة للسعر: حوالى <b>{range_pct:.2f}%</b>
• درجة التقلب الحالية: <b>{vol:.1f} / 100</b>
• نبض السيولة: <b>{liq_text}</b>
• مستوى المخاطر: {risk["emoji"]} <b>{_risk_level_ar(risk["level"])}</b>

📉 <b>المؤشرات الفنية المختصرة (تقديرية):</b>
• قراءة RSI التقديرية: <b>{rsi:.1f}</b> → منطقة {'تشبع بيعى محتمل' if rsi <= 30 else 'حيادية نسبياً'}
• السعر يتحرك داخل نطاق يومى متقلب نسبياً.
• لا توجد إشارة انعكاس مكتملة حتى الآن، لكن الزخم يتغير بسرعة مع الأخبار والسيولة.

⚡️ <b>منظور مضارِبى (قصير المدى):</b>
• دعم حالي محتمل حول: <b>{_format_price(support)}$</b>
• مقاومة قريبة محتملة حول: <b>{_format_price(resistance)}$</b>
• الأفضل حاليًا: أحجام عقود صغيرة + وقف خسارة واضح أسفل مناطق الدعم.

💎 <b>منظور استثمارى (مدى متوسط):</b>
• السوق يتحرك داخل: <b>{phase}</b>
• منطقة دعم عميقة تقريبية (سيناريو هبوطى ممتد): قرب <b>{_format_price(target2)}$</b>
• تأكيد سيناريو صاعد أقوى يكون مع إغلاق أعلى من حوالى: <b>{_format_price(metrics['breakout_level'])}$</b>

📉 <b>مناطق الهبوط المحتملة القادمة (تقديرية وليست مضمونة):</b>
• منطقة حماية أولى: <b>{_format_price(target1)}$</b>
• منطقة دعم عميق / Panic محتمل: <b>{_format_price(target2)}$</b>

🤖 <b>خلاصة IN CRYPTO Ai (نظرة مركزة):</b>
• الاتجاه العام: {phase}
• سلوك السيولة: {liq_text}
• ملخص الحالة الحالية: {phase}

• <b>تقدير حركة 24–72 ساعة (إحتمالات تقريبية):</b>
  - صعود محتمل: ~{p_up}%
  - تماسك جانبى: ~{p_side}%
  - هبوط محتمل: ~{p_drop}%

🏁 <b>التوصية العامة من IN CRYPTO Ai:</b>
• ركّز على حماية رأس المال أولاً قبل البحث عن الفرص.
• تجنب القرارات الانفعالية وقت الأخبار أو حركات الشموع الكبيرة.
• انتظر اختراق أو كسر واضح لمناطق السعر الرئيسية قبل أى دخول عدوانى.
• هذه القراءة ليست توصية بيع أو شراء، وإنما إنذار احترافى مبنى على بيانات السوق.

IN CRYPTO Ai 🤖 — منظومة ذكاء اصطناعى شاملة لتحليل السوق فى الوقت الفعلى.
"""
    return text.strip()


def format_ai_alert_details() -> str:
    """
    تفاصيل إضافية عند الضغط على زر "عرض التفاصيل".
    """
    metrics = get_market_metrics_cached()
    if not metrics:
        return "⚠️ لا توجد بيانات كافية لعرض التفاصيل الآن."

    risk = evaluate_risk_level(
        metrics["change_pct"], metrics["volatility_score"]
    )

    text = f"""
📋 <b>تفاصيل إضافية عن التحذير</b>

• السعر الحالى: <b>${_format_price(metrics["price"])}</b>
• أعلى سعر خلال 24 ساعة: <b>{_format_price(metrics["high"])}$</b>
• أقل سعر خلال 24 ساعة: <b>{_format_price(metrics["low"])}$</b>
• حجم التداول التقديرى: <b>{metrics["volume"]:.3f}</b>

• مدى حركة 24 ساعة: <b>{metrics["range_pct"]:.2f}%</b>
• درجة التقلب: <b>{metrics["volatility_score"]:.1f} / 100</b>
• تقدير RSI: <b>{metrics["rsi_est"]:.1f}</b>
• نبض السيولة: <b>{metrics["liquidity_pulse"]:.2f}</b>

• تقييم المخاطر:
  → {risk["emoji"]} <b>{_risk_level_ar(risk["level"])}</b>
  → {risk["message"]}

⚠️ هذه البيانات لأغراض المتابعة والتحليل وليست توصية استثمارية.
"""
    return text.strip()
