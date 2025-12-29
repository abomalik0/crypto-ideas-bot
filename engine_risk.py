"""
engine_risk.py

✅ الهدف: كل منطق تقييم المخاطر يكون هنا (مستقل عن analysis_engine.py)
علشان:
- نقدر نطوّره بسهولة
- نعرف أي خطأ يطلع من risk منين بالظبط
- يبقى جاهز للربط في engine_smart_snapshot بدون كسر الشغل

ملاحظة: لا يوجد أي تعامل مع توكنات هنا.
"""

from __future__ import annotations

from typing import Any, Dict


def evaluate_risk_level(change_pct: float, volatility_score: float) -> Dict[str, Any]:
    """
    تقييم مستوى المخاطر بناءً على:
      - مقدار التغير اليومي (change_pct)
      - مستوى التقلب (volatility_score 0..100)

    Returns:
      {
        "level": "low"|"medium"|"high",
        "emoji": "...",
        "message": "...",
        "score": float,
        "recommendation": str,
        "max_position_hint": str
      }
    """
    try:
        change = float(change_pct or 0.0)
    except Exception:
        change = 0.0

    try:
        vol = float(volatility_score or 0.0)
    except Exception:
        vol = 0.0

    # نفس منطق analysis_engine تقريباً (متوازن ومستقر)
    risk_score = abs(change) + (vol * 0.4)

    if risk_score < 25:
        level = "low"
        emoji = "🟢"
        message = (
            "المخاطر حاليًا منخفضة نسبيًا، السوق يتحرك بهدوء. "
            "الدخول ممكن بشرط الالتزام بوقف خسارة واضح."
        )
        recommendation = "مسموح بصفقات خفيفة/متوسطة مع إدارة مخاطرة."
        max_position_hint = "يفضل 1x–3x كحد أقصى حسب خبرتك."
    elif risk_score < 50:
        level = "medium"
        emoji = "🟡"
        message = (
            "المخاطر حالياً متوسطة، يوجد تقلب واضح. "
            "يفضل تقليل حجم الصفقة وزيادة الحذر."
        )
        recommendation = "صفقات خفيفة + وقف خسارة قريب + تجنب المبالغة في الرافعة."
        max_position_hint = "يفضل 1x–2x (أو بدون رافعة)."
    else:
        level = "high"
        emoji = "🔴"
        message = (
            "المخاطر حالياً مرتفعة، تقلبات قوية/اندفاع حاد. "
            "يفضل تجنب الدخول العشوائي والتركيز على حماية رأس المال."
        )
        recommendation = "تجنب الدخول أو ادخل بحجم صغير جدًا فقط عند فرصة قوية."
        max_position_hint = "يفضل بدون رافعة أو 1x فقط."

    return {
        "level": level,
        "emoji": emoji,
        "message": message,
        "score": float(risk_score),
        "recommendation": recommendation,
        "max_position_hint": max_position_hint,
    }
