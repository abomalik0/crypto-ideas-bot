"""
engine_risk.py

✅ الهدف: عزل منطق المخاطر (Risk) في ملف مستقل لسهولة التطوير وتحديد الأخطاء بسرعة.
ملاحظة: هذا الملف جاهز للنقل التدريجي من analysis_engine.py بدون كسر الشغل الحالي.
"""

from __future__ import annotations

from engine_metrics import get_market_metrics_cached


def _risk_level_ar(level: str) -> str:
    if level == "low":
        return "منخفض"
    if level == "medium":
        return "متوسط"
    if level == "high":
        return "مرتفع"
    return level


def evaluate_risk_level(change_pct: float, volatility_score: float) -> dict:
    """نفس منطق analysis_engine.py لضمان التطابق عند الربط لاحقًا."""
    risk_score = abs(change_pct) + (volatility_score * 0.4)

    if risk_score < 25:
        level = "low"
        emoji = "🟢"
        message = (
            "المخاطر حاليًا منخفضة نسبيًا، السوق يتحرك بهدوء مع إمكانية "
            "الدخول بشرط الالتزام بمناطق وقف الخسارة."
        )
    elif risk_score < 50:
        level = "medium"
        emoji = "🟡"
        message = (
            "المخاطر حالياً متوسطة، الحركة السعرية بها تقلب واضح، "
            "ويُفضّل تقليل حجم الصفقات واستخدام إدارة مخاطر منضبطة."
        )
    else:
        level = "high"
        emoji = "🔴"
        message = (
            "المخاطر حالياً مرتفعة، السوق يشهد تقلبات قوية أو هبوط حاد، "
            "ويُفضّل تجنب الدخول العشوائى والتركيز على حماية رأس المال."
        )

    return {
        "level": level,
        "emoji": emoji,
        "message": message,
        "score": risk_score,
    }


def format_risk_test() -> str:
    """اختبار سريع مبني على بيتكوين فقط (24h change + volatility)."""
    metrics = get_market_metrics_cached()
    if not metrics:
        return (
            "⚠️ تعذّر جلب بيانات المخاطر حاليًا من المصدر.\n"
            "حاول مرة أخرى بعد قليل."
        )

    change = metrics["change_pct"]
    volatility_score = metrics["volatility_score"]
    risk = evaluate_risk_level(change, volatility_score)

    level_text = _risk_level_ar(risk["level"])

    msg = f"""
⚙️ <b>اختبار المخاطر السريع</b>

تغير البيتكوين خلال 24 ساعة: <b>%{change:+.2f}</b>
درجة التقلب الحالية: <b>{volatility_score:.1f}</b> / 100
المخاطر الحالية: {risk['emoji']} <b>{level_text}</b>

{risk['message']}

💡 هذه القراءة مبنية بالكامل على حركة البيتكوين الحالية بدون أى مزود بيانات إضافى.

<b>IN CRYPTO Ai 🤖 — منظومة ذكاء اصطناعى شاملة لتحليل السوق فى الوقت الفعلى</b>
""".strip()

    return msg
