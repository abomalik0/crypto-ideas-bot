import time
from datetime import datetime

from flask import Flask, request, jsonify, Response

import config
from config import (
    send_message,
    send_message_with_keyboard,
    answer_callback_query,
    add_alert_history,
    log_cleaned_buffer,
    check_admin_auth,
    HTTP_SESSION,
    TELEGRAM_API,
)
from analysis_engine import (
    format_analysis,
    format_market_report,
    format_risk_test,
    format_ai_alert,
    format_ai_alert_details,
    format_weekly_ai_report,
    get_market_metrics_cached,
    evaluate_risk_level,
    detect_alert_condition,
    compute_smart_market_snapshot,
    format_ultra_pro_alert,
    fusion_ai_brain,
    compute_hybrid_pro_core,
    format_school_report,
)
import services

app = Flask(__name__)

# مجموعة الأوامر المعروفة حتى لا تتداخل مع أوامر الرموز (/btcusdt ...)
KNOWN_COMMANDS = {
    "/start",
    "/btc",
    "/vai",
    "/market",
    "/risk_test",
    "/alert",
    "/test_smart",
    "/status",
    "/weekly_now",
    "/add_admin",
    "/remove_admin",
    "/school",
}

# لوحة Inline لمدارس التحليل
SCHOOL_INLINE_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "📘 ICT", "callback_data": "school_ict"},
            {"text": "🎯 SMC", "callback_data": "school_smc"},
        ],
        [
            {"text": "📚 Wyckoff", "callback_data": "school_wyckoff"},
            {"text": "🌀 Harmonic", "callback_data": "school_harmonic"},
        ],
        [
            {"text": "🌊 Elliott Waves", "callback_data": "school_elliott"},
            {"text": "⏱ Time Analysis", "callback_data": "school_time"},
        ],
        [
            {"text": "📈 Price Action", "callback_data": "school_price_action"},
            {"text": "📦 Supply & Demand", "callback_data": "school_sd"},
        ],
        [
            {"text": "🏛 Classical TA", "callback_data": "school_classic"},
            {"text": "💧 Liquidity Map", "callback_data": "school_liquidity"},
        ],
        [
            {"text": "🧬 Market Structure", "callback_data": "school_structure"},
            {"text": "🧭 Multi-Timeframe", "callback_data": "school_multi"},
        ],
        [
            {"text": "📊 Volume & Volatility", "callback_data": "school_volume"},
            {"text": "🧮 Risk & Position", "callback_data": "school_risk"},
        ],
        [
            {"text": "🧠 ALL SCHOOLS", "callback_data": "school_all"},
        ],
    ]
}


# ==============================
#   Helpers صغيرة لـ Smart Alert Test
# ==============================

def _fmt_price(v):
    try:
        if v is None:
            return "-"
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)


def _fmt_pct(v):
    try:
        if v is None:
            return "-"
        return f"{float(v):+.2f}%"
    except Exception:
        return str(v)


def _fmt_num(v):
    try:
        if v is None:
            return "-"
        return f"{float(v):.2f}"
    except Exception:
        return str(v)


def _fmt_secs(v):
    try:
        if v is None:
            return "-"
        v = float(v)
        if v < 1:
            return f"{v:.2f} ثانية"
        return f"{v:.1f} ثانية"
    except Exception:
        return str(v) if v is not None else "-"


def _format_smart_snapshot(snapshot: dict, title: str) -> str:
    """
    تنسيق Snapshot الذكى فى رسالة قصيرة للأدمن (لأمر /test_smart).
    """
    metrics = snapshot.get("metrics") or {}
    risk = snapshot.get("risk") or {}
    pulse = snapshot.get("pulse") or {}
    events = snapshot.get("events") or {}
    alert_level = snapshot.get("alert_level") or {}
    zones = snapshot.get("zones") or {}
    interval = snapshot.get("adaptive_interval")

    price = metrics.get("price")
    change = metrics.get("change_pct")
    range_pct = metrics.get("range_pct")
    vol = metrics.get("volatility_score")
    strength_label = metrics.get("strength_label")
    liquidity_pulse = metrics.get("liquidity_pulse")

    risk_level = risk.get("level")
    risk_emoji = risk.get("emoji", "")
    try:
        from analysis_engine import _risk_level_ar as _rl_txt
        risk_text = _rl_txt(risk_level) if risk_level else "غير معروف"
    except Exception:
        risk_text = "غير معروف"

    regime = pulse.get("regime")
    speed_index = pulse.get("speed_index")
    direction_conf = pulse.get("direction_confidence")

    shock_score = alert_level.get("shock_score")
    level = alert_level.get("level")
    trend_bias = alert_level.get("trend_bias")

    active_labels = events.get("active_labels") or []

    downside_1 = zones.get("downside_zone_1")
    downside_2 = zones.get("downside_zone_2")
    upside_1 = zones.get("upside_zone_1")
    upside_2 = zones.get("upside_zone_2")

    lines: list[str] = []

    lines.append(f"🧪 <b>{title}</b>")
    lines.append("")

    if price is not None:
        lines.append(
            f"• السعر الآن: <b>${_fmt_price(price)}</b> ({_fmt_pct(change)})"
        )
    else:
        lines.append("• السعر الآن: غير متوفر")

    lines.append(
        f"• مدى اليوم ≈ {_fmt_num(range_pct)}٪ / التقلب ≈ {_fmt_num(vol)} / 100"
    )
    lines.append(
        f"• قوة السوق: {strength_label or '-'} / نبض السيولة: {liquidity_pulse or '-'}"
    )
    lines.append(
        f"• وضع التقلب: {regime or '-'} / سرعة الحركة ≈ {_fmt_num(speed_index)} / 100"
    )
    if direction_conf is not None:
        lines.append(f"• ثقة اتجاه قصير المدى ≈ {_fmt_num(direction_conf)} / 100")

    lines.append(
        f"• مستوى المخاطر: {risk_emoji} {risk_text} (score ≈ {_fmt_num(risk.get('score'))})"
    )

    lines.append("")
    lines.append(
        f"• Smart Alert Level: {(str(level).upper() if level else 'NONE')} "
        f"/ Shock Score ≈ {_fmt_num(shock_score)} / 100"
    )
    if trend_bias:
        lines.append(f"• اتجاه قصير المدى: {trend_bias}")

    if active_labels:
        labels_text = ", ".join(active_labels)
        lines.append(f"• أحداث نشطة: {labels_text}")
    else:
        lines.append("• لا توجد أحداث مؤسسية قوية جدًا حاليًا حسب Smart Pulse.")

    if interval is not None:
        lines.append(f"• الفحص التالى المقترح بعد: {_fmt_secs(interval)}")

    if any([downside_1, downside_2, upside_1, upside_2]):
        lines.append("")
        lines.append("• مناطق حركة تقديرية (تعليمية فقط):")

        def _zone_line(label: str, z):
            if not z or len(z) != 2:
                return None
            low, high = z
            try:
                return (
                    f"  - {label}: تقريبًا بين "
                    f"<b>{float(low):,.0f}$</b> و <b>{float(high):,.0f}$</b>"
                )
            except Exception:
                return None

        for label, zone in [
            ("منطقة هبوط 1", downside_1),
            ("منطقة هبوط 2", downside_2),
            ("منطقة صعود 1", upside_1),
            ("منطقة صعود 2", upside_2),
        ]:
            ln = _zone_line(label, zone)
            if ln:
                lines.append(ln)

    reason = snapshot.get("reason")
    if reason:
        lines.append("")
        lines.append("📌 <b>ملخص سريع من Smart Alert:</b>")
        lines.append(reason)

    return "\n".join(lines)


def _format_school_header(code: str) -> str:
    """
    عنوان مختصر فوق تحليل المدرسة. التحليل نفسه تعليمى فقط وليس توصية مباشرة.
    """
    mapping = {
        "ict": "مدرسة ICT – Smart Money Concepts",
        "smc": "مدرسة SMC – Smart Money",
        "wyckoff": "مدرسة Wyckoff – مراحل التجميع والتصريف",
        "harmonic": "مدرسة Harmonic Patterns – نماذج توافقية",
        "elliott": "مدرسة Elliott Waves – موجات إليوت",
        "time": "المدرسة الزمنية – Time Analysis",
        "price_action": "مدرسة Price Action – سلوك السعر",
        "sd": "مدرسة Supply & Demand – مناطق العرض والطلب",
        "classic": "المدرسة الكلاسيكية – ترندات ونماذج",
        "liquidity": "Liquidity Map – خريطة السيولة",
        "structure": "Market Structure – هيكل السوق",
        "multi": "Multi-Timeframe – تعدد الفريمات",
        "volume": "Volume & Volatility – الحجم والتقلب",
        "risk": "Risk & Position – إدارة المخاطر وحجم الصفقة",
        "all": "لوحة مدارس التحليل",
    }
    title = mapping.get(code.lower(), "تحليل مدرسة")
    return (
        f"📘 <b>{title}</b>\n"
        "⚠️ هذا التحليل تعليمى فقط وليس توصية مباشرة بالشراء أو البيع.\n\n"
    )


NO_SCHOOL_ANALYSIS_MARKERS = (
    "لا يوجد تحليل متاح حاليًا لهذه المدرسة",
    "لا يوجد تحليل متاح حاليا لهذه المدرسة",
    "No analysis is available for this school",
)


def _get_school_snapshot(symbol: str):
    """
    Helper لقراءة لقطة سريعة للسوق لاستخدامها فى قوالب المدارس.
    """
    symbol = (symbol or "BTCUSDT").upper()
    if not symbol.endswith("USDT") and len(symbol) <= 5:
        symbol = symbol + "USDT"

    try:
        snapshot = compute_smart_market_snapshot(symbol)
    except TypeError:
        # بعض الإصدارات لا تستقبل الرمز
        snapshot = compute_smart_market_snapshot()
    except Exception as e:
        config.logger.exception("compute_smart_market_snapshot failed for %s: %s", symbol, e)
        snapshot = None

    if not isinstance(snapshot, dict):
        return None

    metrics = snapshot.get("metrics") or {}
    risk = snapshot.get("risk") or {}

    price = metrics.get("price")
    change = metrics.get("change_pct")
    vol = metrics.get("volatility_score")
    range_pct = metrics.get("range_pct")
    liquidity = metrics.get("liquidity_pulse")
    trend = metrics.get("strength_label") or metrics.get("trend_label")

    risk_level = (risk or {}).get("level")
    risk_score = (risk or {}).get("score")

    def _fmt(x):
        try:
            if x is None:
                return "غير متاح"
            if isinstance(x, float):
                return f"{x:.2f}"
            return str(x)
        except Exception:
            return str(x)

    return {
        "symbol": symbol,
        "price": price,
        "change": change,
        "range_pct": range_pct,
        "volatility": vol,
        "liquidity": liquidity,
        "trend": trend or "غير واضح",
        "risk_level": risk_level or "غير محدد",
        "risk_score": risk_score if isinstance(risk_score, (int, float)) else None,
        "fmt": _fmt,
    }


def _build_smc_template(s):
    f = s["fmt"]
    sym = s["symbol"]
    direction = s["trend"]
    change = f(s["change"])
    rng = f(s["range_pct"])
    vol = f(s["volatility"])
    risk_level = s["risk_level"]
    risk_score = f(s["risk_score"] or 0)

    return (
        f"📘 مدرسة SMC — تحليل {sym}\n"
        "🔍 مقدمة:\n"
        "مدرسة SMC تركز على قراءة الهيكلة (Market Structure) وكسر الاتجاه (BOS / CHoCH) "
        "ومناطق الطلب/العرض (POI) وعدم التوازن السعرى (Imbalance). الفكرة الأساسية أن السعر يتحرك "
        "بين مناطق مؤسسية محددة ثم يعود لملء الفراغات قبل استكمال الاتجاه.\n\n"
        "📊 قراءة الهيكلة الحالية:\n"
        f"• اتجاه الهيكلة التقريبى: <b>{direction}</b>\n"
        f"• التغير اليومى: ~ <b>{change}%</b> مع مدى حركة حوالى <b>{rng}%</b>\n"
        f"• درجة التقلب: {vol} / 10\n\n"
        "📉 عدم التوازن (Imbalance):\n"
        "• وجود مناطق سعرية لم تُختبر بالكامل يشير لاحتمال عودة السعر لها قبل استكمال الحركة.\n"
        "• يُفضل انتظار Mitigation واضح قبل أى دخول قوى.\n\n"
        "🎯 مناطق الطلب والعرض (POI):\n"
        "• ابحث عن آخر مناطق Demand أسفل السعر الجارى، وآخر مناطق Supply أعلى السعر، "
        "مع ربطها بهيكلة الفريم الأكبر.\n\n"
        "📈 سيناريو تعليمى صاعد (Bullish SMC):\n"
        "• انتظار تصحيح إلى منطقة Demand قوية متوافقة مع BOS سابق، ثم ظهور CHoCH صاعد كإشارة تأكيد.\n"
        "• الأهداف تكون قرب قمم سابقة أو مناطق Imbalance غير مملوءة.\n\n"
        "📉 سيناريو تعليمى هابط (Bearish SMC):\n"
        "• كسر واضح لهيكلة الصعود وتحولها إلى LH/LL مع اختبار منطقة Supply أعلى السعر.\n"
        "• الأهداف قرب القيعان السابقة أو مناطق طلب غير مختبرة.\n\n"
        "⚠️ إدارة المخاطرة فى SMC:\n"
        f"• مستوى المخاطرة الحالى: <b>{risk_level}</b> (Score ≈ {risk_score}/10).\n"
        "• لا تعتمد على منطقة واحدة للدخول؛ لازم توافق بين الهيكلة + POI + سلوك الشموع.\n"
    )


def _build_wyckoff_template(s):
    f = s["fmt"]
    sym = s["symbol"]
    direction = s["trend"]
    change = f(s["change"])
    rng = f(s["range_pct"])
    risk_level = s["risk_level"]

    return (
        f"📘 مدرسة Wyckoff — تحليل {sym}\n"
        "🔍 مقدمة:\n"
        "وايكوف تركز على مراحل السوق (Accumulation / Distribution) وكيف تتحرك المؤسسات داخل النطاقات "
        "السعرية قبل الانطلاق. الهدف هو فهم أين يتم التجميع وأين يحدث التصريف.\n\n"
        "📊 قراءة المرحلة الحالية (تعليمية):\n"
        f"• الاتجاه الغالب: <b>{direction}</b> مع تغير يومى يقارب <b>{change}%</b> ومدى حركة ~ <b>{rng}%</b>.\n"
        "• لو الحركة جانبية مع ذيول قوية عند الأطراف؛ غالبًا نحن داخل Trading Range.\n\n"
        "🎭 أهم أحداث Wyckoff (SC / AR / ST / Spring / UT):\n"
        "• راقب القيعان الحادة كـ Selling Climax، ثم الارتداد الأول كـ Automatic Rally، "
        "ثم إعادة الاختبار ST داخل النطاق.\n"
        "• ظهور Spring أو Upthrust عند حدود الرينج غالبًا يسبق حركة قوية فى الاتجاه المعاكس.\n\n"
        "📈 سيناريو صاعد (Accumulation):\n"
        "• تكوّن نطاق أفقى بعد هبوط، مع زيادة حجم الشراء قرب القاع، ثم اختراق الحد العلوى للرنج وتثبيت السعر فوقه.\n\n"
        "📉 سيناريو هابط (Distribution):\n"
        "• نطاق أفقى بعد صعود، مع قمم متقاربة وضعف اختراقات، ثم كسر الحد السفلى للرنج مع زيادة فى الحجم البيعى.\n\n"
        "⚠️ ملاحظات إدارة المخاطرة:\n"
        f"• مستوى المخاطرة التقريبى: <b>{risk_level}</b>.\n"
        "• لا يُفضّل الدخول من منتصف الرينج؛ الأفضل من قرب الحدود مع تأكيد حجم التداول.\n"
    )


def _build_harmonic_template(s):
    f = s["fmt"]
    sym = s["symbol"]
    change = f(s["change"])
    rng = f(s["range_pct"])

    return (
        f"📘 مدرسة Harmonic — تحليل {sym}\n"
        "🔍 مقدمة:\n"
        "التحليل التوافقى يعتمد على تتبع الموجات وفق نسب فيبوناتشى لتحديد نماذج XABCD "
        "ومناطق انعكاس محتملة (PRZ).\n\n"
        "🎼 الفكرة الحالية (تعليمية):\n"
        f"• الحركة الأخيرة أظهرت تغيرًا يوميًا يقارب <b>{change}%</b> ومدى حوالى <b>{rng}%</b>، "
        "ويمكن النظر لها كموجة CD محتملة داخل نموذج أكبر.\n\n"
        "📐 منطقة الانعكاس (PRZ):\n"
        "• راقب تلاقى مستويات فيبوناتشى للنموذج (مثل 0.786 XA + 1.27 BC + 1.618 CD) لتحديد نطاق ضيق للمراقبة.\n"
        "• ظهور شموع انعكاسية قوية داخل هذا النطاق يزيد من احتمال نجاح النموذج.\n\n"
        "📈 سيناريو صاعد:\n"
        "• اكتمال نموذج Bullish داخل PRZ أسفل السعر الحالى مع رفض قوى للهبوط.\n\n"
        "📉 سيناريو هابط:\n"
        "• اكتمال نموذج Bearish أعلى السعر الحالى مع كسور كاذبة ثم عودة داخل النطاق.\n\n"
        "⚠️ ملاحظات:\n"
        "• النماذج التوافقية لا تُستخدم وحدها؛ الأفضل دمجها مع SMC أو Wyckoff أو Price Action.\n"
    )


def _build_time_template(s):
    f = s["fmt"]
    sym = s["symbol"]
    rng = f(s["range_pct"])
    vol = f(s["volatility"])

    return (
        f"⏱ المدرسة الزمنية – تحليل {sym}\n"
        "🔍 الفكرة الأساسية:\n"
        "المدرسة الزمنية تهتم بإيقاع السوق والدورات الزمنية (Cycles) أكثر من شكل النموذج السعرى نفسه.\n\n"
        "📊 إيقاع الحركة الحالى:\n"
        f"• المدى اليومى التقريبى: <b>{rng}%</b> مع درجة تقلب حوالى {vol} / 10.\n"
        "• يمكن اعتبار ذلك دورة نشاط متوسطة؛ ليست هادئة جدًا ولا عنيفة جدًا.\n\n"
        "🕒 استخدام التوقيت فى القرارات:\n"
        "• التركيز على أوقات فتح الجلسات الرئيسية ومواعيد الأخبار عالية التأثير.\n"
        "• عدم الدخول قبل دقائق قليلة من الأخبار؛ انتظر إغلاق أول شمعة بعدها لتقييم الاتجاه.\n"
    )


def _build_volume_template(s):
    f = s["fmt"]
    sym = s["symbol"]
    change = f(s["change"])
    rng = f(s["range_pct"])
    vol = f(s["volatility"])
    liq = f(s["liquidity"])

    return (
        f"📊 مدرسة الحجم والتقلب – تحليل {sym}\n"
        "🔍 نظرة عامة:\n"
        "هذه المدرسة تدمج بين قراءة حجم التداول (Volume) ودرجة التقلب (Volatility) "
        "لفهم قوة الحركة واحتمال استمرارها.\n\n"
        "📊 الوضع الحالى:\n"
        f"• التغير اليومى: <b>{change}%</b> ومدى حركة تقريبى <b>{rng}%</b>.\n"
        f"• درجة التقلب: {vol} / 10 – نبض السيولة: {liq} / 10 (قيم تقريبية من المحرك).\n\n"
        "📈 عندما يكون الحجم والتقلب مرتفعين معًا → حركة قوية تحتاج انضباط فى إدارة المخاطر.\n"
        "📉 عندما يكونان منخفضين → سوق هادئ يميل للتذبذب والرنجات الجانبية.\n"
    )


def _build_generic_school_template(code: str, s):
    sym = s["symbol"]
    change = s["fmt"](s["change"])
    rng = s["fmt"](s["range_pct"])
    return (
        f"📚 تحليل تعليمى لمدرسة {code.upper()} على {sym}.\n"
        f"التغير اليومى التقريبى: ~ {change}% ضمن مدى ~ {rng}%.\n"
        "استخدم قواعد هذه المدرسة فى قراءة الاتجاه والمناطق مع احترام إدارة رأس المال.\n"
    )



def _build_ict_template(s):
    f = s["fmt"]
    sym = s["symbol"]
    change = f(s["change"])
    rng = f(s["range_pct"])
    vol = f(s["volatility"])
    risk = f(s["risk_score"] or 0)
    risk_level = s["risk_level"]
    trend = s["trend"]

    return (
        f"📘 مدرسة ICT – تحليل {sym}\n"
        "🔍 مقدمة:\n"
        "مدرسة ICT تركز على مفهوم PD Arrays (Premium / Discount)، الفجوات (Fair Value Gaps)، "
        "والجلسات الزمنية (Sessions) لاصطياد تحركات المؤسسات. الفكرة الأساسية: الشراء من مناطق الخصم "
        "والبيع من مناطق البريميوم مع احترام التوقيت والمؤشرات على السيولة.\n\n"
        "📊 نظرة سريعة على السوق:\n"
        f"• الاتجاه التقريبى: <b>{trend}</b> مع تغير يومى ~ <b>{change}%</b> ومدى حركة ~ <b>{rng}%</b>.\n"
        f"• درجة التقلب الحالية: {vol} / 10 – كلما زادت زاد احتمال ظهور فخاخ سيولة.\n"
        f"• تقييم المخاطرة: <b>{risk_level}</b> (≈ {risk}/10).\n\n"
        "🧭 خريطة الـ PD Arrays (تعليمية):\n"
        "• اعتبر السعر الحالى منتصف نطاق تعليمى؛ ما فوقه منطقة Premium وما تحته Discount.\n"
        "• فرص الشراء الأفضل تكون من مناطق Discount المتوافقة مع FVG + POI.\n"
        "• فرص البيع تكون من مناطق Premium المتوافقة مع سيولة متراكمة فوق قمم واضحة.\n\n"
        "💧 خريطة السيولة (Liquidity):\n"
        "• ابحث عن قمم وقيعان واضحة على الفريمات الصغيرة؛ غالبًا سيتم تصفيتها قبل الانعكاس.\n"
        "• لا تدخل مباشرة بعد الكسر؛ انتظر عودة السعر لإعادة اختبار المستوى أو FVG قريبة.\n\n"
        "🕒 التوقيت (Sessions):\n"
        "• أقوى الحركات عادة تكون خلال جلسات لندن/نيويورك.\n"
        "• تجنب الدخول قبل الأخبار عالية التأثير حيث تزيد الفجوات والانزلاقات.\n\n"
        "⚠️ ملاحظات إدارة المخاطرة:\n"
        "• لا تدخل صفقة لمجرد ظهور FVG؛ لازم توافق بين: PD Array + Liquidity + Timing.\n"
        "• اجعل وقف الخسارة خلف قمة/قاع منطقى وليس قريبًا جدًا من الدخول.\n"
    )


def _build_elliott_template(s):
    f = s["fmt"]
    sym = s["symbol"]
    change = f(s["change"])
    rng = f(s["range_pct"])
    vol = f(s["volatility"])
    trend = s["trend"]

    return (
        f"🌊 مدرسة Elliott Waves – تحليل {sym}\n"
        "🔍 مقدمة:\n"
        "إليوت تعتمد على تقسيم حركة السوق إلى موجات دافعة (1–5) ومصححة (A–B–C)، "
        "مع احترام نسب فيبوناتشى للعلاقات بين الموجات. الهدف هو تحديد أين نقف داخل الدورة الموجية.\n\n"
        "📊 صورة الموجة الحالية (تعليمية):\n"
        f"• الاتجاه العام: <b>{trend}</b> مع تغير يومى ~ <b>{change}%</b> ومدى ~ <b>{rng}%</b>.\n"
        f"• درجة التقلب: {vol} / 10 – تساعد على تمييز إن كانت الحركة موجة دافعة أم تصحيحية.\n\n"
        "📈 موجات دافعة محتملة:\n"
        "• لو الحركة واضحة فى اتجاه واحد مع قمم وقيعان متصاعدة/هابطة بانتظام، "
        "يمكن اعتبارها موجة 3 أو 5 دافعة.\n"
        "• راقب مناطق 38.2% – 61.8% فيبو كتصحيحات نموذجية للموجة 2 أو 4.\n\n"
        "📉 موجات تصحيحية (A–B–C):\n"
        "• بعد حركة قوية، ظهور هيكلة متعرجة غالبًا يمثل تصحيح زجزاج أو فلات.\n"
        "• اكتمال الموجة C قرب امتدادات 100% – 161.8% لموجة A يعد منطقة مراقبة للعكس.\n\n"
        "⚠️ نصائح استخدام إليوت:\n"
        "• لا تحاول عدّ الموجات على كل حركة صغيرة؛ ركّز على الفريمات المتوسطة أولًا.\n"
        "• الأفضل دمج عدّ الموجة مع SMC أو الكلاسيكى لتأكيد مناطق الانعكاس.\n"
    )


def _build_price_action_template(s):
    f = s["fmt"]
    sym = s["symbol"]
    change = f(s["change"])
    rng = f(s["range_pct"])
    vol = f(s["volatility"])
    trend = s["trend"]

    return (
        f"📈 مدرسة Price Action – تحليل {sym}\n"
        "🔍 مقدمة:\n"
        "الـ Price Action يركز على قراءة حركة الشموع ومستويات الدعم والمقاومة بدون مؤشرات معقدة. "
        "الفكرة: السعر هو المؤشر الأقوى.\n\n"
        "📊 نظرة سريعة:\n"
        f"• الاتجاه العام: <b>{trend}</b> مع تغير يومى ~ <b>{change}%</b> ومدى ~ <b>{rng}%</b>.\n"
        f"• درجة التقلب: {vol} / 10 – تحدد نوع الأنماط المتوقعة (رنج / ترند).\n\n"
        "🧱 مناطق رئيسية:\n"
        "• حدد قمم وقيعان يومية وأسبوعية مهمة واعتمد عليها كنقاط قرار.\n"
        "• راقب الإغلاقات فوق/تحت هذه المستويات بدلًا من ذيول الشموع فقط.\n\n"
        "🕯 أنماط شموع مهمة:\n"
        "• Pin Bar / Engulfing / Inside Bar حول المناطق الرئيسية تعطي فرصًا عالية الاحتمال.\n"
        "• تجنب التداول على أنماط منفصلة فى منتصف الحركة بدون مستوى واضح.\n\n"
        "⚠️ إدارة المخاطرة:\n"
        "• لا تدخل إلا عندما يجتمع: مستوى واضح + إشارة شمعة + اتجاه عام داعم.\n"
        "• يفضّل أن يكون وقف الخسارة خلف آخر قمة/قاع واضح وليس داخل الضوضاء.\n"
    )


def _build_sd_template(s):
    f = s["fmt"]
    sym = s["symbol"]
    change = f(s["change"])
    rng = f(s["range_pct"])
    trend = s["trend"]

    return (
        f"📦 مدرسة Supply & Demand – تحليل {sym}\n"
        "🔍 مقدمة:\n"
        "تركز هذه المدرسة على تحديد مناطق تجمع الأوامر الشرائية (Demand) والبيعية (Supply) "
        "حيث يتدخل اللاعبون الكبار بقوة.\n\n"
        "📊 وضع السوق الحالى:\n"
        f"• الاتجاه التقريبى: <b>{trend}</b> مع تغير ~ <b>{change}%</b> ومدى ~ <b>{rng}%</b>.\n\n"
        "🎯 مناطق محتملة:\n"
        "• Demand: مناطق انعكاس قوية بعد هبوط حاد يعقبه صعود سريع.\n"
        "• Supply: مناطق انعكاس قوية بعد صعود حاد يعقبه هبوط سريع.\n"
        "• الأفضل الاعتماد على المناطق الحديثة على الفريمات الأعلى (4H / Daily).\n\n"
        "⚠️ نصائح:\n"
        "• لا تدخل من منتصف المنطقة؛ حاول الاقتراب من بداية الـ Zone مع تأكيد Price Action.\n"
        "• كثرة لمس المنطقة تضعفها؛ المنطقة الأقوى غالبًا تكون Fresh أو لم تُزر إلا مرة قليلة.\n"
    )


def _build_classic_template(s):
    f = s["fmt"]
    sym = s["symbol"]
    change = f(s["change"])
    rng = f(s["range_pct"])
    vol = f(s["volatility"])
    trend = s["trend"]

    return (
        f"🏛 المدرسة الكلاسيكية – تحليل {sym}\n"
        "🔍 مقدمة:\n"
        "التحليل الكلاسيكى يعتمد على خطوط الاتجاه، النماذج السعرية (مثل المثلثات والرايات)، "
        "والمتوسطات المتحركة والدعوم والمقاومات.\n\n"
        "📊 الوضع الحالى:\n"
        f"• الاتجاه العام: <b>{trend}</b> مع تغير ~ <b>{change}%</b> ومدى ~ <b>{rng}%</b>.\n"
        f"• درجة التقلب: {vol} / 10 — تساعد على معرفة صلاحية النماذج.\n\n"
        "📐 أمثلة تطبيقية:\n"
        "• فى حالة ترند واضح: يتم استخدام خطوط اتجاه لمتابعة القيعان/القمم.\n"
        "• فى حالة نطاق: ابحث عن نماذج مثل المثلث أو الراية التى قد تسبق الانطلاق.\n\n"
        "⚠️ ملاحظات:\n"
        "• النماذج الكلاسيكية تحتاج تأكيد بالكسر والإغلاق وليس مجرد لمس المستوى.\n"
        "• يفضّل دمجها مع الحجم لمعرفة قوة الاختراق.\n"
    )


def _build_liquidity_template(s):
    f = s["fmt"]
    sym = s["symbol"]
    change = f(s["change"])
    rng = f(s["range_pct"])
    liq = f(s["liquidity"])
    trend = s["trend"]

    return (
        f"💧 مدرسة Liquidity Map – تحليل {sym}\n"
        "🔍 مقدمة:\n"
        "هذه المدرسة تركز على تتبع أماكن تراكم الأوامر (السيولة) فوق القمم وتحت القيعان "
        "لتوقع أين يمكن أن يتحرك السعر قبل الانعكاس.\n\n"
        "📊 نظرة عامة:\n"
        f"• الاتجاه التقريبى: <b>{trend}</b> مع تغير ~ <b>{change}%</b> ومدى ~ <b>{rng}%</b>.\n"
        f"• نبض السيولة من المحرك: {liq} / 10 (قيمة تعليمية).\n\n"
        "💧 نقاط سيولة محتملة:\n"
        "• قمم متتالية لم تُكسر منذ فترة غالبًا تحتوى على سيولة بيع.\n"
        "• قيعان متتالية لم تُكسر قد تحتوى على سيولة شراء.\n"
        "• غالبًا يتم ضرب هذه المناطق قبل الانعكاس لإخراج المتأخرين من السوق.\n\n"
        "⚠️ تذكير:\n"
        "• لا تعتمد على السيولة وحدها؛ دمجها مع SMC أو ICT يعطى نتائج أفضل.\n"
    )


def _build_structure_template(s):
    f = s["fmt"]
    sym = s["symbol"]
    change = f(s["change"])
    rng = f(s["range_pct"])
    trend = s["trend"]

    return (
        f"🧬 مدرسة Market Structure – تحليل {sym}\n"
        "🔍 مقدمة:\n"
        "تركيز هذه المدرسة على قراءة تسلسل القمم والقيعان لفهم الاتجاه والتحولات الرئيسية "
        "(HH / HL / LH / LL).\n\n"
        "📊 ملخص الهيكلة الحالية:\n"
        f"• الاتجاه التقريبى: <b>{trend}</b> مع تغير ~ <b>{change}%</b> ومدى ~ <b>{rng}%</b>.\n\n"
        "📈 إرشادات تعليمية:\n"
        "• HH + HL → اتجاه صاعد؛ الأفضل البحث عن فرص شراء بعد التصحيحات.\n"
        "• LH + LL → اتجاه هابط؛ الأفضل البحث عن فرص بيع بعد التصحيحات.\n"
        "• كسر واضح لآخر قمة/قاع غالبًا يمثّل تغييرًا فى الهيكلة (CHoCH / BOS).\n"
    )


def _build_multi_template(s):
    f = s["fmt"]
    sym = s["symbol"]
    change = f(s["change"])
    rng = f(s["range_pct"])
    trend = s["trend"]

    return (
        f"🧭 مدرسة Multi-Timeframe – تحليل {sym}\n"
        "🔍 مقدمة:\n"
        "التحليل متعدد الأطر يربط بين الفريم الكبير (الاتجاه العام) والمتوسط والصغير "
        "لضبط نقاط الدخول والخروج بدقة.\n\n"
        "📊 فكرة تطبيقية:\n"
        f"• الاتجاه الكلى (حسب المحرك): <b>{trend}</b> مع تغير ~ <b>{change}%</b> ومدى ~ <b>{rng}%</b>.\n"
        "• يُنصح بتحديد Bias من الفريم اليومى، ثم البحث عن مناطق الدخول على 4H / 1H، "
        "وأخيرًا تنفيذ الصفقة على 15m / 5m.\n\n"
        "⚠️ نصائح:\n"
        "• لا تعاكس الفريم الأكبر لمجرد إشارة على الفريم الصغير.\n"
        "• توافق الاتجاه بين 3 فريمات على الأقل يعطي فرصة أعلى جودة.\n"
    )


def _build_risk_template(s):
    f = s["fmt"]
    sym = s["symbol"]
    change = f(s["change"])
    rng = f(s["range_pct"])
    risk = f(s["risk_score"] or 0)
    risk_level = s["risk_level"]

    return (
        f"🧮 مدرسة Risk & Position – تحليل {sym}\n"
        "🔍 مقدمة:\n"
        "هذه المدرسة لا تهتم باتجاه السعر فقط، بل بحجم الصفقة والمخاطرة المقبولة "
        "والانكشاف على السوق.\n\n"
        "📊 تقييم المخاطرة الحالى (من المحرك):\n"
        f"• مستوى عام: <b>{risk_level}</b> (≈ {risk} / 10).\n"
        f"• التغير اليومى التقريبى: {change}% ضمن مدى ~ {rng}%.\n\n"
        "📐 قواعد تعليمية لإدارة الصفقة:\n"
        "• لا تخاطر بأكثر من 1–2٪ من رأس المال فى الصفقة الواحدة.\n"
        "• حجم العقد = (نسبة المخاطرة × رأس المال) ÷ (المسافة بين الدخول ووقف الخسارة).\n"
        "• تجنب فتح صفقات كثيرة فى نفس الاتجاه على نفس الأصل (Overexposure).\n"
    )


def _build_all_schools_template(s):
    sym = s["symbol"]
    trend = s["trend"]
    f = s["fmt"]
    change = f(s["change"])
    rng = f(s["range_pct"])
    risk = f(s["risk_score"] or 0)
    risk_level = s["risk_level"]

    return (
        f"🧠 نظرة شاملة — ALL SCHOOLS على {sym}\n"
        "هذا الملخص يجمع أهم الأفكار من المدارس المختلفة بشكل تعليمى:\n\n"
        f"• الاتجاه العام (Market Structure): <b>{trend}</b> مع تغير ~ {change}% ومدى ~ {rng}%.\n"
        f"• تقييم المخاطرة من المحرك: <b>{risk_level}</b> (≈ {risk}/10).\n\n"
        "📘 SMC / ICT / Wyckoff:\n"
        "• استخدم الهيكلة لمعرفة الاتجاه، والـ PD Arrays / Liquidity لتحديد مناطق دخول محتملة.\n\n"
        "📈 الكلاسيكى / Price Action / Harmonic / Elliott:\n"
        "• النماذج والشموع تساعدك على توقيت الدخول من نفس المناطق.\n\n"
        "🧮 Risk & Position:\n"
        "• جودة التحليل بدون إدارة مخاطر جيدة لا تكفى؛ ركّز على حجم العقد ونسبة المخاطرة.\n"
    )


def _build_school_report(code: str, symbol: str) -> str:
    """ Wrapper موحد لبناء نص تحليل المدرسة. يعيد دائمًا نصًا جاهزًا للإرسال. """
    code = (code or "").lower()
    symbol = symbol or "BTCUSDT"

    # 1) نحاول أولاً المحرك الأصلى format_school_report
    body = None
    try:
        body = format_school_report(code, symbol=symbol)
    except Exception as e:
        config.logger.exception("Error in format_school_report(%s, %s): %s", code, symbol, e)
        body = None

    if isinstance(body, str):
        text = body.strip()
        if text and not any(marker in text for marker in NO_SCHOOL_ANALYSIS_MARKERS):
            return text

    # 2) لو مفيش مخرجات مفيدة من المحرك → نبنى قالب تعليمى اعتمادًا على لقطة السوق
    snapshot = _get_school_snapshot(symbol)
    if not snapshot:
        return (
            "⚠️ لا توجد بيانات كافية لإعداد تحليل مفصل لهذه المدرسة حاليًا.\n"
            "حاول استخدام رمز مختلف أو مدرسة أخرى."
        )

    # مدارس لها قوالب خاصة
    if code == "smc":
        return _build_smc_template(snapshot)
    if code == "wyckoff":
        return _build_wyckoff_template(snapshot)
    if code == "harmonic":
        return _build_harmonic_template(snapshot)
    if code in {"time", "time_analysis"}:
        return _build_time_template(snapshot)
    if code in {"volume", "vol"}:
        return _build_volume_template(snapshot)
    if code == "ict":
        return _build_ict_template(snapshot)
    if code == "elliott":
        return _build_elliott_template(snapshot)
    if code in {"price_action", "pa"}:
        return _build_price_action_template(snapshot)
    if code in {"sd", "supply_demand"}:
        return _build_sd_template(snapshot)
    if code in {"classic", "classical"}:
        return _build_classic_template(snapshot)
    if code == "liquidity":
        return _build_liquidity_template(snapshot)
    if code in {"structure", "market_structure"}:
        return _build_structure_template(snapshot)
    if code in {"multi", "multi_tf", "multi_timeframe"}:
        return _build_multi_template(snapshot)
    if code in {"risk", "risk_position"}:
        return _build_risk_template(snapshot)
    if code == "all":
        return _build_all_schools_template(snapshot)

    # لو كود مختلف أو جديد نرجع قالب عام
    return _build_generic_school_template(code, snapshot)

def webhook():
    update = request.get_json(force=True, silent=True) or {}
    config.LAST_WEBHOOK_TICK = time.time()

    # ⭐ Auto register من أول أى Update
    try:
        config.auto_register_from_update(update)
    except Exception:
        pass
    # ⭐ END

    if config.BOT_DEBUG:
        config.logger.info("Update: %s", update)
    else:
        config.logger.debug("Update keys: %s", list(update.keys()))

    # callback_query
    if "callback_query" in update:
        cq = update["callback_query"]
        callback_id = cq.get("id")
        data = cq.get("data")
        message = cq.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        from_user = cq.get("from") or {}
        from_id = from_user.get("id")

        if callback_id:
            answer_callback_query(callback_id)

        # تفاصيل التحذير
        if data == "alert_details":
            if from_id != config.ADMIN_CHAT_ID:
                if chat_id:
                    send_message(chat_id, "❌ هذا الزر مخصص للإدارة فقط.")
                return jsonify(ok=True)

            details = format_ai_alert_details()
            send_message(chat_id, details)
            return jsonify(ok=True)

        # مدارس التحليل – Inline Keyboard
        if data and data.startswith("school_"):
            code = data.split("school_", 1)[1]
            try:
                header = _format_school_header(code)
            except Exception:
                header = "📚 تحليل مدرسة.\n\n"

            try:
                # حالياً نستخدم BTCUSDT كمحرك رئيسى للمدارس
                body = _build_school_report(code, symbol="BTCUSDT")
            except Exception as e:
                config.logger.exception("Error in school callback analysis: %s", e)
                body = "⚠️ حدث خطأ أثناء توليد التحليل من المحرك."

            send_message(chat_id, header + (body or ""))
            return jsonify(ok=True)

        return jsonify(ok=True)

    # رسائل عادية
    if "message" not in update:
        return jsonify(ok=True)

    msg = update["message"]
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    lower_text = text.lower()

    # تسجيل الشات + حفظه على الملف (لو جديد)
    config.register_known_chat(chat_id)

    # تجهيز نظام الأدمنات الإضافيين فى runtime لو مش موجود
    if not hasattr(config, "EXTRA_ADMINS"):
        config.EXTRA_ADMINS = set()

    is_owner = (chat_id == config.ADMIN_CHAT_ID)
    is_admin = is_owner or (chat_id in config.EXTRA_ADMINS)

    # ==============================
    #           /start
    # ==============================
    if lower_text == "/start":
        # رسالة المستخدم الأساسية
        user_block = (
            "👋✨ أهلاً بك فى <b>IN CRYPTO Ai</b>.\n"
            "منظومة <b>ذكاء اصطناعى</b> تتابع حركة <b>البيتكوين</b> والسوق لحظيًا "
            "وتقدّم لك رؤية واضحة بدون تعقيد.\n\n"
            "📌 <b>أوامر المستخدم:</b>\n"
            "• <code>/btc</code> — تحليل لحظى للبيتكوين (BTCUSDT)\n"
            "• اكتب أى زوج بالشكل: <code>/btcusdt</code>، <code>/ethusdt</code>، <code>/cfxusdt</code>\n"
            "• <code>/market</code> — نظرة عامة على حالة السوق اليوم\n"
            "• <code>/risk_test</code> — اختبار بسيط لإدارة المخاطر\n"
            "• <code>/school</code> — فتح لوحة مدارس التحليل (ICT / Wyckoff / Harmonic / Elliott / Time ...)\n\n"
            "💡 <b>ملاحظة مهمة:</b>\n"
            "كل التحليلات تعليمية ومساعدة لاتخاذ القرار، وليست توصية مباشرة بالشراء أو البيع.\n"
        )

        # بلوك أوامر الأدمن يظهر فقط للأدمن / الأونر
        admin_block = ""
        if is_admin:
            admin_block = (
                "\n📌 <b>أوامر الإدارة:</b>\n"
                "• <code>/alert</code> — إرسال تحذير Ultra PRO V16 (اختبار كامل لنظام التحذير)\n"
                "• <code>/test_smart</code> — فحص Smart Alert Snapshot اللحظى\n"
                "• <code>/status</code> — حالة النظام (APIs / Threads / مخاطر)\n"
                "• <code>/weekly_now</code> — إرسال التقرير الأسبوعى الآن لكل الشاتات\n"
            )

            if is_owner:
                admin_block += (
                    "\n<b>إدارة الصلاحيات (Owner فقط):</b>\n"
                    "• <code>/add_admin &lt;chat_id&gt;</code> — إضافة أدمن جديد\n"
                    "• <code>/remove_admin &lt;chat_id&gt;</code> — إزالة أدمن حالي\n"
                )

            admin_block += (
                "\n<b>لوحة التحكم (Dashboard):</b>\n"
                "• <a href=\"https://dizzy-bab-incrypto-free-258377c4.koyeb.app//admin/dashboard?pass=ahmed123\">فتح لوحة التحكم من هنا</a>\n"
            )

        welcome = user_block + admin_block
        send_message(chat_id, welcome)
        return jsonify(ok=True)

    # ==============================
    #       أوامر إدارة الأدمنات
    # ==============================
    if lower_text.startswith("/add_admin"):
        if not is_owner:
            send_message(chat_id, "❌ هذا الأمر مخصص لمالك النظام فقط.")
            return jsonify(ok=True)

        parts = text.split()
        if len(parts) < 2:
            send_message(
                chat_id,
                "⚠️ استخدم الأمر هكذا:\n"
                "<code>/add_admin 123456789</code> (ضع chat_id المراد إضافته)",
            )
            return jsonify(ok=True)

        target_raw = parts[1].strip()
        if not target_raw.isdigit():
            send_message(chat_id, "⚠️ الـ chat_id يجب أن يكون أرقام فقط.")
            return jsonify(ok=True)

        target_id = int(target_raw)

        if target_id == config.ADMIN_CHAT_ID:
            send_message(chat_id, "ℹ️ هذا المستخدم هو الـ Owner بالفعل.")
            return jsonify(ok=True)

        if target_id in config.EXTRA_ADMINS:
            send_message(chat_id, "ℹ️ هذا الـ chat_id مُسجّل بالفعل كأدمن.")
            return jsonify(ok=True)

        config.EXTRA_ADMINS.add(target_id)
        send_message(
            chat_id,
            f"✅ تم إضافة <code>{target_id}</code> كأدمن بنجاح (يُطبّق من نفس اللحظة).",
        )
        return jsonify(ok=True)

    if lower_text.startswith("/remove_admin"):
        if not is_owner:
            send_message(chat_id, "❌ هذا الأمر مخصص لمالك النظام فقط.")
            return jsonify(ok=True)

        parts = text.split()
        if len(parts) < 2:
            send_message(
                chat_id,
                "⚠️ استخدم الأمر هكذا:\n"
                "<code>/remove_admin 123456789</code> (ضع chat_id المراد إزالته)",
            )
            return jsonify(ok=True)

        target_raw = parts[1].strip()
        if not target_raw.isdigit():
            send_message(chat_id, "⚠️ الـ chat_id يجب أن يكون أرقام فقط.")
            return jsonify(ok=True)

        target_id = int(target_raw)

        if target_id == config.ADMIN_CHAT_ID:
            send_message(chat_id, "❌ لا يمكن إزالة الـ Owner من قائمة الصلاحيات.")
            return jsonify(ok=True)

        if target_id not in config.EXTRA_ADMINS:
            send_message(chat_id, "ℹ️ هذا الـ chat_id غير موجود فى قائمة الأدمن حالياً.")
            return jsonify(ok=True)

        config.EXTRA_ADMINS.remove(target_id)
        send_message(
            chat_id,
            f"✅ تم إزالة <code>{target_id}</code> من قائمة الأدمن.",
        )
        return jsonify(ok=True)

    # ==============================
    #       أوامر المستخدم العادى
    # ==============================

    if lower_text == "/btc":
        # التحليل الأساسى من المحرك القديم (مع كاش) – BTCUSDT
        base_text = services.get_cached_response(
            "btc_analysis", lambda: format_analysis("BTCUSDT")
        )

        header = ""
        try:
            snapshot = compute_smart_market_snapshot()
        except Exception as e:
            config.logger.exception("Error in /btc snapshot: %s", e)
            snapshot = None

        if snapshot:
            metrics = snapshot.get("metrics") or {}
            risk = snapshot.get("risk") or {}

            price = metrics.get("price")
            change = metrics.get("change_pct")
            vol = metrics.get("volatility_score")
            range_pct = metrics.get("range_pct")

            try:
                fusion = fusion_ai_brain(metrics, risk)
            except Exception as e:
                config.logger.exception("fusion_ai_brain error in /btc: %s", e)
                fusion = None

            from analysis_engine import _risk_level_ar as _rl_txt
            risk_level = (risk or {}).get("level")
            risk_emoji = (risk or {}).get("emoji", "")
            risk_name = _rl_txt(risk_level) if risk_level else "غير معروف"

            bias_text = fusion["bias_text"] if fusion and "bias_text" in fusion else "لا توجد قراءة اتجاه واضحة."
            strength_label = metrics.get("strength_label", "-")
            liquidity_pulse = metrics.get("liquidity_pulse", "-")

            if price is not None:
                try:
                    p = float(price)
                    ch = float(change or 0.0)
                    v = float(vol or 0.0)
                    r = float(range_pct or 0.0)
                    header = (
                        "🧭 <b>ملخص سريع لوضع البيتكوين الآن:</b>\n"
                        f"• السعر اللحظى: <b>${p:,.0f}</b> | تغير 24 ساعة: <b>{ch:+.2f}%</b>\n"
                        f"• قوة التقلب: <b>{v:.1f}</b> / 100 | مدى اليوم ≈ <b>{r:.2f}%</b>\n"
                        f"• قوة الحركة: {strength_label}\n"
                        f"• نبض السيولة: {liquidity_pulse}\n"
                        f"• الاتجاه العام حسب الذكاء الاصطناعى: {bias_text}\n"
                        f"• مستوى المخاطر: {risk_emoji} <b>{risk_name}</b>\n\n"
                    )
                except Exception as e:
                    config.logger.exception("Header format error in /btc: %s", e)

        reply = header + base_text
        send_message(chat_id, reply)
        return jsonify(ok=True)

    if lower_text == "/vai":
        reply = format_analysis("VAIUSDT")
        send_message(chat_id, reply)
        return jsonify(ok=True)

    if lower_text == "/market":
        reply = services.get_cached_response("market_report", format_market_report)
        send_message(chat_id, reply)
        return jsonify(ok=True)

    if lower_text == "/risk_test":
        reply = services.get_cached_response("risk_test", format_risk_test)
        send_message(chat_id, reply)
        return jsonify(ok=True)

    # لوحة مدارس التحليل
    if lower_text.startswith("/school"):
        # شكل 1: /school  → يفتح لوحة المدارس على BTCUSDT
        parts = text.split()
        if len(parts) == 1:
            send_message_with_keyboard(
                chat_id,
                "📚 اختر مدرسة التحليل التى تريدها.\n"
                "كل مدرسة لها طريقة مختلفة فى قراءة السوق واتخاذ القرار.\n\n"
                "💡 يمكنك أيضًا طلب تحليل مباشر بالصيغة:\n"
                "<code>/school smc btc</code> أو <code>/school wyckoff ethusdt</code>",
                SCHOOL_INLINE_KEYBOARD,
            )
            return jsonify(ok=True)

        # شكل 2: /school ict btcusdt  → تحليل مدرسة + عملة مباشرة
        school_raw = parts[1].lower()
        sym = parts[2] if len(parts) >= 3 else "BTCUSDT"

        aliases = {
            "ict": "ict",
            "smc": "smc",
            "wyckoff": "wyckoff",
            "harmonic": "harmonic",
            "elliott": "elliott",
            "eliott": "elliott",
            "time": "time",
            "time_analysis": "time",
            "pa": "price_action",
            "price": "price_action",
            "price_action": "price_action",
            "sd": "sd",
            "supply": "sd",
            "classic": "classic",
            "ta": "classic",
            "liquidity": "liquidity",
            "liq": "liquidity",
            "structure": "structure",
            "ms": "structure",
            "multi": "multi",
            "mtf": "multi",
            "volume": "volume",
            "vol": "volume",
            "volatility": "volume",
            "risk": "risk",
            "risk_position": "risk",
            "rm": "risk",
            "all": "all",
        }

        # حدد الكود النهائي للمدرسة من الـ aliases
        code = aliases.get(school_raw, school_raw)

        # هيدر الرسالة
        try:
            header = _format_school_header(code)
        except Exception as e:
            config.logger.exception("Error building _format_school_header: %s", e)
            header = "📚 تحليل مدرسة.\n\n"

        # جسم الرسالة
        try:
            body = _build_school_report(code, symbol=sym)
        except Exception as e:
            config.logger.exception("Error in /school direct command: %s", e)
            body = (
                "⚠️ حدث خطأ أثناء توليد تحليل المدرسة.\n"
                "🔁 جرّب اختيار المدرسة مرة أخرى من /school."
            )

        send_message(chat_id, header + (body or ""))
        return jsonify(ok=True)

# ==============================
    #      أوامر الإدارة (Admin)
    # ==============================

    # ===== أمر /alert — الآن اختبار Ultra PRO للأدمن فقط =====
    if lower_text == "/alert":
        if not is_admin:
            send_message(chat_id, "❌ هذا الأمر مخصص للإدارة فقط.")
            return jsonify(ok=True)

        try:
            alert_text = format_ultra_pro_alert()
        except Exception as e:
            config.logger.exception("format_ultra_pro_alert failed: %s", e)
            alert_text = None

        if not alert_text:
            alert_text = services.get_cached_response("alert_text", format_ai_alert)

        # إرسال فقط فى شات الأدمن اللى نفّذ الأمر (اختبار كامل لنظام التحذير)
        try:
            send_message(chat_id, alert_text)
        except Exception as e:
            config.logger.exception("Error sending /alert to admin chat: %s", e)

        add_alert_history(
            "manual_ultra_test",
            "Manual /alert (ADMIN TEST ONLY, no broadcast)",
        )

        return jsonify(ok=True)

    # ==============================
    #   /test_smart — تشخيص Smart Alert (للأدمن فقط)
    # ==============================
    if lower_text == "/test_smart":
        if not is_admin:
            send_message(chat_id, "❌ هذا الأمر مخصص للإدارة فقط.")
            return jsonify(ok=True)

        try:
            snapshot = compute_smart_market_snapshot()
        except Exception as e:
            config.logger.exception("Error in /test_smart snapshot: %s", e)
            send_message(
                chat_id,
                "⚠️ حدث خطأ أثناء بناء Smart Alert Snapshot.\n"
                "راجع لوحة التحكم / اللوج لمزيد من التفاصيل.",
            )
            return jsonify(ok=True)

        if not snapshot:
            send_message(
                chat_id,
                "⚠️ لم أستطع بناء Snapshot للسوق حالياً (قد تكون مشكلة بيانات أو API).",
            )
            return jsonify(ok=True)

        msg_real = _format_smart_snapshot(snapshot, "Smart Alert — LIVE SNAPSHOT")
        send_message(chat_id, msg_real)

        metrics = snapshot.get("metrics") or {}
        add_alert_history(
            "smart_test",
            "Manual /test_smart snapshot",
            price=metrics.get("price"),
            change=metrics.get("change_pct"),
        )

        return jsonify(ok=True)

    # ==============================
    #   /status — حالة النظام (أدمن فقط)
    # ==============================
    if lower_text == "/status":
        if not is_admin:
            send_message(chat_id, "❌ هذا الأمر مخصص للإدارة فقط.")
            return jsonify(ok=True)

        metrics = get_market_metrics_cached()
        if metrics:
            change = metrics["change_pct"]
            vol = metrics["volatility_score"]
            risk = evaluate_risk_level(change, vol)
            from analysis_engine import _risk_level_ar as _rl_txt
            risk_text = (
                f"{risk['emoji']} {_rl_txt(risk['level'])}" if risk else "N/A"
            )
        else:
            risk_text = "N/A"

        msg_status = f"""
🛰 <b>حالة نظام IN CRYPTO Ai</b>

• حالة Binance: {"✅" if config.API_STATUS["binance_ok"] else "⚠️"}
• حالة KuCoin: {"✅" if config.API_STATUS["kucoin_ok"] else "⚠️"}
• آخر فحص API: {config.API_STATUS.get("last_api_check")}

• آخر تحديث Real-Time: {config.REALTIME_CACHE.get("last_update")}
• آخر Webhook: {datetime.utcfromtimestamp(config.LAST_WEBHOOK_TICK).isoformat(timespec="seconds") if config.LAST_WEBHOOK_TICK else "لا يوجد"}

• حالة المخاطر العامة: {risk_text}

• عدد الشاتات المسجلة: {len(config.KNOWN_CHAT_IDS)}
• آخر تقرير أسبوعى مبعوت: {config.LAST_WEEKLY_SENT_DATE}
• آخر Auto Alert (قديم): {config.LAST_AUTO_ALERT_INFO.get("time")} ({config.LAST_AUTO_ALERT_INFO.get("reason")})
""".strip()
        send_message(chat_id, msg_status)
        return jsonify(ok=True)

    # أمر اختبار /weekly_now للأدمن (من خلال الخدمات الجديدة)
    if lower_text == "/weekly_now":
        if not is_admin:
            send_message(chat_id, "❌ هذا الأمر مخصص للإدارة فقط.")
            return jsonify(ok=True)

        services.handle_admin_weekly_now_command(chat_id)
        return jsonify(ok=True)

    # ==============================
    #   أوامر الرموز العامة: /btcusdt /ethusdt /cfxusdt ...
    # ==============================
    if text.startswith("/"):
        # ناخد أول كلمة فى الرسالة، ونحوّلها لسيمبل
        first_part = text.split()[0]
        cmd_lower = first_part.lower()

        if cmd_lower not in KNOWN_COMMANDS:
            symbol = first_part[1:].upper()  # شيل "/" وخلى الباقى كابتل
            # نسمح حاليًا فقط بأزواج USDT عشان ما نتخبطش فى أوامر تانية
            if symbol.endswith("USDT") and len(symbol) > 5:
                try:
                    reply = format_analysis(symbol)
                except Exception as e:
                    config.logger.exception("Error in generic symbol analysis: %s", e)
                    reply = f"⚠️ حدث خطأ أثناء تحليل <b>{symbol}</b>."

                send_message(chat_id, reply)
                return jsonify(ok=True)

    # أى رسالة أخرى حالياً نتجاهلها / أو ممكن تضيف معالجة بعدين
    return jsonify(ok=True)


# ==============================
#   /auto_alert Endpoint (النظام القديم)
# ==============================

@app.route("/auto_alert", methods=["GET"])
def auto_alert():
    """
    نظام التحذير القديم المعتمد على detect_alert_condition.
    ما زال موجود للتوافق الخلفى / dashboards قديمة.
    """
    metrics = get_market_metrics_cached()
    if not metrics:
        config.logger.warning("auto_alert: metrics is None")
        return jsonify(ok=False, error="metrics_failed"), 200

    risk = evaluate_risk_level(metrics["change_pct"], metrics["volatility_score"])

    reason = detect_alert_condition(metrics, risk)
    if not reason:
        config.logger.info("auto_alert: no condition met.")
        config.LAST_AUTO_ALERT_INFO = {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "reason": "no_condition",
            "sent": False,
        }
        return jsonify(ok=True, alert_sent=False, reason="no_condition"), 200

    if config.LAST_ALERT_REASON == reason:
        config.logger.info("auto_alert: same reason as last alert, skip.")
        config.LAST_AUTO_ALERT_INFO = {
            "time": datetime.utcnow().isoformat(timespec="seconds"),
            "reason": "duplicate_reason",
            "sent": False,
        }
        return (
            jsonify(ok=True, alert_sent=False, reason="duplicate_reason"),
            200,
        )

    text = format_ai_alert()
    send_message(config.ADMIN_CHAT_ID, text)

    config.LAST_ALERT_REASON = reason
    config.LAST_AUTO_ALERT_INFO = {
        "time": datetime.utcnow().isoformat(timespec="seconds"),
        "reason": reason,
        "sent": True,
    }
    config.logger.info("auto_alert: NEW alert sent! reason=%s", reason)

    add_alert_history(
        "auto",
        reason,
        price=metrics["price"],
        change=metrics["change_pct"],
    )

    return jsonify(ok=True, alert_sent=True, reason="sent"), 200


# ==============================
#   مسارات اختبار / Admin / Dashboard
# ==============================

@app.route("/test_alert", methods=["GET"])
def test_alert():
    try:
        alert_message = (
            "🚨 *تنبيه تجريبي من السيرفر*\n"
            "تم إرسال هذا التنبيه لاختبار النظام.\n"
            "كل شيء شغال بنجاح 👍"
        )
        send_message(config.ADMIN_CHAT_ID, alert_message, parse_mode="Markdown")
        return {"ok": True, "sent": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.route("/dashboard_api", methods=["GET"])
def dashboard_api():
    if not check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    metrics = get_market_metrics_cached()
    if not metrics:
        return jsonify(ok=False, error="metrics_failed"), 200

    risk = evaluate_risk_level(
        metrics["change_pct"], metrics["volatility_score"]
    )

    from analysis_engine import _risk_level_ar as _rl_txt

    pro_core = None
    try:
        pro_core = compute_hybrid_pro_core()
    except Exception as e:
        config.logger.exception("dashboard_api: compute_hybrid_pro_core failed: %s", e)
        pro_core = None

    return jsonify(
        ok=True,
        price=metrics["price"],
        change_pct=metrics["change_pct"],
        range_pct=metrics["range_pct"],
        volatility_score=metrics["volatility_score"],
        strength_label=metrics["strength_label"],
        liquidity_pulse=metrics["liquidity_pulse"],
        risk_level=_rl_txt(risk["level"]),
        risk_emoji=risk["emoji"],
        risk_message=risk["message"],
        last_auto_alert=config.LAST_AUTO_ALERT_INFO,
        last_error=config.LAST_ERROR_INFO,
        last_weekly_sent=config.LAST_WEEKLY_SENT_DATE,
        known_chats=len(config.KNOWN_CHAT_IDS),
        api_status=config.API_STATUS,
        last_realtime_tick=config.LAST_REALTIME_TICK,
        last_weekly_tick=config.LAST_WEEKLY_TICK,
        last_webhook_tick=config.LAST_WEBHOOK_TICK,
        last_watchdog_tick=config.LAST_WATCHDOG_TICK,
        last_smart_alert_tick=config.LAST_SMART_ALERT_TICK,
        pro_alert_core=pro_core,
    )


@app.route("/admin/dashboard", methods=["GET"])
def admin_dashboard():
    if not check_admin_auth(request):
        return Response("Unauthorized", status=401)

    try:
        with open("dashboard.html", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        html = "<h1>dashboard.html غير موجود فى نفس مجلد bot.py</h1>"

    return Response(html, mimetype="text/html")


@app.route("/admin/logs", methods=["GET"])
def admin_logs():
    if not check_admin_auth(request):
        return Response("Unauthorized", status=401)
    content = log_cleaned_buffer()
    return Response(content, mimetype="text/plain")


@app.route("/admin/alerts_history", methods=["GET"])
def admin_alerts_history():
    if not check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    return jsonify(
        ok=True,
        alerts=list(config.ALERTS_HISTORY),
    )


@app.route("/admin/clear_alerts", methods=["GET"])
def admin_clear_alerts():
    if not check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    config.ALERTS_HISTORY.clear()
    config.logger.info("Admin cleared alerts history from dashboard.")
    return jsonify(ok=True, message="تم مسح سجل التحذيرات.")


@app.route("/admin/force_alert", methods=["GET"])
def admin_force_alert():
    if not check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    text = format_ultra_pro_alert() or format_ai_alert()
    send_message(config.ADMIN_CHAT_ID, text)
    add_alert_history("force", "Force alert from admin dashboard")
    config.logger.info("Admin forced alert from dashboard.")
    return jsonify(ok=True, message="تم إرسال التحذير الفورى للأدمن.")


@app.route("/admin/test_alert", methods=["GET"])
def admin_test_alert():
    if not check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    test_msg = (
        "🧪 <b>تنبيه تجريبى من لوحة التحكم</b>\n"
        "هذا التنبيه للتأكد من أن نظام الإشعارات يعمل بشكل سليم."
    )
    send_message(config.ADMIN_CHAT_ID, test_msg)
    config.logger.info("Admin sent test alert from dashboard.")
    return jsonify(ok=True, message="تم إرسال تنبيه تجريبى للأدمن.")


@app.route("/weekly_ai_report", methods=["GET"])
def weekly_ai_report():
    sent_to = services.send_weekly_report_to_all_chats()
    return jsonify(ok=True, sent_to=sent_to)


@app.route("/admin/weekly_ai_test", methods=["GET"])
def admin_weekly_ai_test():
    if not check_admin_auth(request):
        return jsonify(ok=False, error="unauthorized"), 401

    report = services.get_cached_response("weekly_report", format_weekly_ai_report)
    send_message(config.ADMIN_CHAT_ID, report)
    config.logger.info("Admin requested weekly AI report test.")
    return jsonify(
        ok=True,
        message="تم إرسال التقرير الأسبوعى التجريبى للأدمن فقط.",
    )


# ==============================
#   /status API (للإدارة أو للمراقبة)
# ==============================

@app.route("/status", methods=["GET"])
def status_api():
    import threading as _th

    threads = [t.name for t in _th.enumerate()]

    return jsonify(
        ok=True,
        api_status=config.API_STATUS,
        realtime_last_tick=config.LAST_REALTIME_TICK,
        weekly_last_tick=config.LAST_WEEKLY_TICK,
        webhook_last_tick=config.LAST_WEBHOOK_TICK,
        watchdog_last_tick=config.LAST_WATCHDOG_TICK,
        smart_alert_last_tick=config.LAST_SMART_ALERT_TICK,
        cache_last_update=config.REALTIME_CACHE.get("last_update"),
        last_auto_alert=config.LAST_AUTO_ALERT_INFO,
        last_weekly_sent=config.LAST_WEEKLY_SENT_DATE,
        known_chats=len(config.KNOWN_CHAT_IDS),
        threads=threads,
    )


# ==============================
#       تفعيل الـ Webhook
# ==============================

def setup_webhook():
    webhook_url = f"{config.APP_BASE_URL}/webhook"
    try:
        r = HTTP_SESSION.get(
            f"{TELEGRAM_API}/setWebhook",
            params={"url": webhook_url},
            timeout=10,
        )
        config.logger.info("Webhook response: %s - %s", r.status_code, r.text)
    except Exception as e:
        config.logger.exception("Error while setting webhook: %s", e)


def set_webhook_on_startup():
    setup_webhook()


# =====================================
# تشغيل البوت — Main Runner
# =====================================

if __name__ == "__main__":
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    # تحميل السناك شوت (لو متفعّل)
    try:
        services.load_snapshot()
    except Exception as e:
        logging.exception("Snapshot load failed on startup: %s", e)

    # ضبط الويب هوك
    try:
        set_webhook_on_startup()
    except Exception as e:
        logging.exception("Failed to set webhook on startup: %s", e)

    # تشغيل كل الثريدات من services
    try:
        services.start_background_threads()
    except Exception as e:
        logging.exception("Failed to start background threads: %s", e)

    # تشغيل Flask
    app.run(host="0.0.0.0", port=8080)
