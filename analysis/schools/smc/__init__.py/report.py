"""
SMC — Smart Money Concepts
Advanced Institutional Style Report
"""

from typing import Dict, Any


def generate_smc_report(symbol: str, snapshot: Dict[str, Any]) -> str:
    """
    Generate a professional SMC report using market snapshot.
    This function DOES NOT place trades — analysis only.
    """

    # ===== Basic Safety =====
    if not snapshot:
        return (
            "📘 SMC — Smart Money Concepts\n"
            "⚠️ لا توجد بيانات كافية لتحليل SMC حاليًا."
        )

    # ===== Extract Core Data =====
    price = snapshot.get("price")
    htf_trend = snapshot.get("htf_trend", "غير واضح")
    ltf_trend = snapshot.get("ltf_trend", "غير واضح")

    bos = snapshot.get("bos", "غير متوفر")
    choch = snapshot.get("choch", "غير متوفر")

    buy_liq = snapshot.get("buy_liquidity", "غير محدد")
    sell_liq = snapshot.get("sell_liquidity", "غير محدد")
    sweep = snapshot.get("liquidity_sweep", "لا يوجد")

    fvg = snapshot.get("fvg_zone", "غير محددة")
    mitigated = snapshot.get("fvg_mitigated", "غير معروف")

    bias = snapshot.get("institutional_bias", "محايد")

    # ===== Build Report =====
    report = f"""
📘 SMC — Smart Money Concepts — تحليل {symbol}

━━━━━━━━━━━━━━━━━━
🔍 مقدمة:
تحليل حركة السعر من منظور المؤسسات (Smart Money)،
مع التركيز على الهيكلة، السيولة، ومناطق التفاعل الحقيقية.

━━━━━━━━━━━━━━━━━━
📊 الهيكلة السعرية:
• اتجاه الإطار الكبير (HTF): {htf_trend}
• اتجاه الإطار الصغير (LTF): {ltf_trend}
• آخر BOS: {bos}
• آخر CHoCH: {choch}

━━━━━━━━━━━━━━━━━━
💧 السيولة (Liquidity):
• Buy-side Liquidity: {buy_liq}
• Sell-side Liquidity: {sell_liq}
• Liquidity Sweep: {sweep}

━━━━━━━━━━━━━━━━━━
📉 Imbalance & FVG:
• أقرب FVG: {fvg}
• حالة الـ Mitigation: {mitigated}

━━━━━━━━━━━━━━━━━━
🎯 الانحياز المؤسسي:
• Institutional Bias: {bias}

━━━━━━━━━━━━━━━━━━
⚠️ ملاحظة:
هذا التحليل تعليمي فقط وليس توصية مباشرة بالبيع أو الشراء.
"""

    return report.strip()
