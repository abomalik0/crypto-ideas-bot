"""
Schools Registry
================
• Minimal registry for backtesting
• Harmonic only
"""

# ❌ ممنوع استيراد SMC / ICT أثناء الباكتيست
# from analysis.schools.smc.report import generate_smc_report

# ✅ لو حابب تسيبها فاضية
SCHOOL_REGISTRY = {}

def run_school(school: str, symbol: str, snapshot: dict) -> str:
    school = (school or "").lower().strip()
    fn = SCHOOL_REGISTRY.get(school)

    if not callable(fn):
        return f"⚠️ المدرسة '{school}' غير مدعومة حالياً."

    return fn(symbol, snapshot)
